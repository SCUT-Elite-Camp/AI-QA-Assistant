"""Build and optionally activate a Wiki revision from a verified human review."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from eval.wiki.export_review_bundle import main as export_review_bundle
from eval.wiki.verify_gate_c_full_submission import TABLES, validate
from storage.wiki_review_release import create_reviewed_revision
from storage.wiki_store import WikiStore


def _read_review(archive: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(archive) as zipped:
        return {
            name: list(csv.DictReader(io.StringIO(
                zipped.read(f"{name}-human-reviewed.csv").decode("utf-8-sig")
            ))) for name in TABLES
        }


def _verify_database_matches_bundle(database: Path, revision: str, bundle: Path) -> None:
    """Reject a release if the reviewed export and source SQLite differ."""
    expected = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["files"]
    with tempfile.TemporaryDirectory(prefix="wiki-review-check-") as directory:
        exported = Path(directory) / "bundle"
        with contextlib.redirect_stdout(io.StringIO()):
            export_review_bundle([
                str(database), "--revision", revision, "--output-dir", str(exported),
            ])
        for name in TABLES:
            filename = f"{name}.csv"
            if hashlib.sha256((exported / filename).read_bytes()).hexdigest() != expected[filename]:
                raise ValueError(f"source Wiki revision differs from human review: {name}")


def select_reviewed_pages(tables: dict[str, list[dict[str, str]]]) -> dict[str, set[str]]:
    """Keep only complete pages whose content and upstream identity passed review."""
    approved_candidates = {
        row["candidate_id"] for row in tables["01-candidates"]
        if row["promotion_status"] == "PROMOTED" and all(
            row[field].strip().upper() == "TRUE" for field in (
                "human_candidate_valid", "human_type_valid", "human_promotion_valid",
            )
        )
    }
    approved_identities = {
        row["identity_id"] for row in tables["02-identities"]
        if row["human_identity_valid"].strip().upper() == "TRUE"
        and row["human_merge_valid"].strip().upper() == "TRUE"
        and set(json.loads(row["candidate_ids_json"])) <= approved_candidates
    }
    claims_by_page: dict[str, list[dict[str, str]]] = {}
    for row in tables["04-final-claims"]:
        claims_by_page.setdefault(row["page_id"], []).append(row)
    bad_event_pages = {
        row["page_id"] for row in tables["05-audit-events"]
        if row["human_event_valid"].strip().upper() != "TRUE"
    }
    bad_repair_pages = {
        row["page_id"] for row in tables["06-repair-events"]
        if row["human_repair_valid"].strip().upper() != "TRUE"
    }
    selected_pages = set()
    for row in tables["03-pages"]:
        page_id = row["page_id"]
        claims = claims_by_page.get(page_id, [])
        if (row["status"] == "REVIEWING"
                and row["human_page_worthy"].strip().upper() == "TRUE"
                and row["human_summary_supported"].strip().upper() == "TRUE"
                and (not row["identity_id"] or row["identity_id"] in approved_identities)
                and (row["page_type"] == "INDEX" or claims)
                and all(claim["human_supported"].strip().upper() == "TRUE" for claim in claims)
                and page_id not in bad_event_pages and page_id not in bad_repair_pages):
            selected_pages.add(page_id)
    used_identities = {
        row["identity_id"] for row in tables["03-pages"]
        if row["page_id"] in selected_pages and row["identity_id"]
    }
    used_candidates = {
        candidate_id for row in tables["02-identities"]
        if row["identity_id"] in used_identities
        for candidate_id in json.loads(row["candidate_ids_json"])
    }
    if not selected_pages - {row["page_id"] for row in tables["03-pages"]
                             if row["page_type"] == "INDEX"}:
        raise ValueError("human review leaves no content page to publish")
    return {"pages": selected_pages, "identities": used_identities,
            "candidates": used_candidates}


def _verify_subset(
    store: WikiStore, source_revision: str, release_revision: str,
    selected: dict[str, set[str]],
) -> dict[str, int]:
    """Check exact membership, original Claim/Evidence rows, and live links."""
    with store.connection() as db:
        pages = db.execute(
            "SELECT page_id,slug,payload FROM wiki_page_revisions WHERE revision=?",
            (release_revision,),
        ).fetchall()
        page_ids = {row["page_id"] for row in pages}
        slugs = {row["slug"] for row in pages}
        if page_ids != selected["pages"]:
            raise ValueError("reviewed Wiki page membership changed")
        for table, column, expected in (
            ("wiki_identities", "identity_id", selected["identities"]),
            ("wiki_candidates", "candidate_id", selected["candidates"]),
        ):
            actual = {row[0] for row in db.execute(
                f"SELECT {column} FROM {table} WHERE revision=?", (release_revision,),
            )}
            if actual != expected:
                raise ValueError(f"reviewed Wiki {table} membership changed")
        for row in pages:
            payload = json.loads(row["payload"])
            if not set(payload.get("links") or []) <= page_ids:
                raise ValueError("reviewed Wiki contains a dead page link")
            rendered = [payload.get("summary") or ""]
            rendered.extend(claim.get("rendered_text") or ""
                            for section in payload.get("sections") or []
                            for claim in section.get("claims") or [])
            if any(slug not in slugs for text in rendered
                   for slug in re.findall(r"\]\(/wiki/([^)]*)\)", text)):
                raise ValueError("reviewed Wiki contains a dead rendered link")
        for table, columns in (
            ("wiki_page_claims", "page_id,claim_id,section_heading,claim_text,verdict,reason_code,reason"),
            ("wiki_page_sources", "page_id,claim_id,source_id,document_id,document_version_id,"
             "section_id,evidence_id,support_quote,quote_start,quote_end,evidence_sha256"),
        ):
            original = {
                tuple(row) for row in db.execute(
                    f"SELECT {columns} FROM {table} WHERE revision=? AND page_id IN "
                    f"({','.join('?' for _ in page_ids)})",
                    (source_revision, *sorted(page_ids)),
                )
            }
            release = {tuple(row) for row in db.execute(
                f"SELECT {columns} FROM {table} WHERE revision=?", (release_revision,),
            )}
            if original != release:
                raise ValueError(f"reviewed Wiki changed {table} content or Evidence")
        return {"pages": len(pages), "claims": db.execute(
            "SELECT COUNT(*) FROM wiki_page_claims WHERE revision=?", (release_revision,),
        ).fetchone()[0]}


def prepare(
    database: Path, bundle: Path, archive: Path, provenance: Path,
    output_database: Path, *, activate: bool = False,
) -> dict:
    """Create a separate release DB; never edit the reviewed DRAFT or source DB."""
    if output_database.exists():
        raise FileExistsError(f"refusing to overwrite release database: {output_database}")
    review = validate(bundle, archive)
    signed = json.loads(provenance.read_text(encoding="utf-8"))
    if (signed.get("archive_sha256") != review["archive_sha256"]
            or signed.get("archive_integrity") != "PASS"
            or not signed.get("reviewer_identity_reported_by_user")
            or not signed.get("review_completed_on_reported_by_user")):
        raise ValueError("human review provenance does not match the verified archive")
    revision = review["revision"]
    _verify_database_matches_bundle(database, revision, bundle)
    selected = select_reviewed_pages(_read_review(archive))
    with sqlite3.connect(database) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute(
            "SELECT source_scope,owner_id,knowledge_base_id,status FROM wiki_build_runs "
            "WHERE revision=?", (revision,),
        ).fetchall()
        if len(rows) != 1 or rows[0]["status"] != "DRAFT":
            raise ValueError("reviewed source revision must be one unchanged DRAFT")
        scope = {key: rows[0][key] for key in (
            "source_scope", "owner_id", "knowledge_base_id",
        )}
        output_database.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(output_database) as target:
                source.backup(target)
        except BaseException:
            output_database.unlink(missing_ok=True)
            raise
    try:
        _verify_database_matches_bundle(output_database, revision, bundle)
        store = WikiStore(output_database)
        release_revision = create_reviewed_revision(
            store, **scope, source_revision=revision,
            review_sha256=review["archive_sha256"], page_ids=selected["pages"],
            identity_ids=selected["identities"], candidate_ids=selected["candidates"],
            reviewer=signed["reviewer_identity_reported_by_user"],
            reviewed_on=signed["review_completed_on_reported_by_user"],
        )
        counts = _verify_subset(store, revision, release_revision, selected)
        if activate:
            store.publish_revision(**scope, revision=release_revision)
        return {
            "source_revision": revision, "release_revision": release_revision,
            "review_archive_sha256": review["archive_sha256"],
            "reviewer": signed["reviewer_identity_reported_by_user"],
            "review_date": signed["review_completed_on_reported_by_user"],
            "status": "PUBLISHED_IN_RELEASE_DATABASE" if activate else "DRAFT_PREPARED",
            "production_visible": False, "gate_c": "PARTIAL", "gate_d": "NOT_RUN",
            "selected": {key: len(value) for key, value in selected.items()},
            "excluded_pages": review["row_counts"]["03-pages"] - counts["pages"],
            "release_counts": counts, "subset_consistency": "PASS",
            "scope": scope, "database": str(output_database),
        }
    except BaseException:
        output_database.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--activate", action="store_true",
                        help="Publish only inside the separate output database")
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f"refusing to overwrite release report: {args.report}")
    result = prepare(args.database, args.bundle, args.archive, args.provenance,
                     args.output_db, activate=args.activate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
