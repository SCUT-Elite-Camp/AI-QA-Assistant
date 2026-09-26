"""Export a private, trace-complete Wiki review bundle from one draft revision."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Wiki structure and claim review material")
    parser.add_argument("database", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite review bundle: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(args.database) as db:
        db.row_factory = sqlite3.Row
        runs = db.execute(
            "SELECT * FROM wiki_build_runs WHERE revision=?", (args.revision,),
        ).fetchall()
        if len(runs) != 1:
            raise ValueError("revision must resolve to exactly one Wiki scope")
        run = runs[0]
        context = (run["source_scope"], run["owner_id"], run["knowledge_base_id"], args.revision)
        candidates = [
            json.loads(row["payload"]) for row in db.execute(
                "SELECT payload FROM wiki_candidates WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? ORDER BY candidate_id", context,
            )
        ]
        identities = [dict(row) for row in db.execute(
            "SELECT * FROM wiki_identities WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? ORDER BY kind,canonical_name", context,
        )]
        aliases_by_identity: dict[str, list[str]] = defaultdict(list)
        for row in db.execute(
            "SELECT identity_id,alias FROM wiki_identity_aliases WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? ORDER BY identity_id,alias", context,
        ):
            aliases_by_identity[row["identity_id"]].append(row["alias"])
        for item in identities:
            item["aliases"] = aliases_by_identity[item["identity_id"]]
        pages = [dict(row) for row in db.execute(
            "SELECT r.page_id,r.page_type,r.title,r.slug,r.identity_id,r.status,r.summary,r.payload "
            "FROM wiki_page_revisions r "
            "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? AND r.revision=? "
            "ORDER BY r.page_type,r.title", context,
        )]
        claims = _claim_rows(db, context)
        audits = [dict(row) for row in db.execute(
            "SELECT * FROM wiki_claim_audits WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? ORDER BY page_id,audit_round,claim_id", context,
        )]
        repairs = [dict(row) for row in db.execute(
            "SELECT * FROM wiki_claim_repairs WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? ORDER BY page_id,repair_round,original_claim_id", context,
        )]

    identity_conflicts = _cross_kind_identity_conflicts(identities)
    _write_candidates(args.output_dir / "01-candidates.csv", candidates)
    _write_identities(args.output_dir / "02-identities.csv", identities, identity_conflicts)
    _write_pages(args.output_dir / "03-pages.csv", pages)
    _write_csv(args.output_dir / "04-final-claims.csv", claims)
    _write_csv(args.output_dir / "05-audit-events.csv", [_json_fields(row, "source_ids") for row in audits])
    _write_csv(args.output_dir / "06-repair-events.csv", [_json_fields(row, "source_ids") for row in repairs])
    (args.output_dir / "07-pages.json").write_text(
        json.dumps([json.loads(row["payload"]) for row in pages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stats = _stats(run, candidates, identities, pages, claims, audits, repairs, identity_conflicts)
    (args.output_dir / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (args.output_dir / "README.md").write_text(_readme(args.revision), encoding="utf-8")
    manifest = {
        "revision": args.revision,
        "files": {
            path.name: _sha256(path) for path in sorted(args.output_dir.iterdir()) if path.is_file()
        },
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    archive = args.output_dir.with_suffix(".zip")
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite review archive: {archive}")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(args.output_dir.iterdir()):
            target.write(path, arcname=path.name)
    print(json.dumps({
        "status": "EXPORTED", "revision": args.revision, "claims": len(claims),
        "audit_events": len(audits), "repair_events": len(repairs),
        "output": str(archive),
    }, ensure_ascii=False))
    return 0


def _claim_rows(db: sqlite3.Connection, context: tuple[str, str, str, str]) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT r.title,r.page_type,c.page_id,c.section_heading,c.claim_id,c.claim_text,c.verdict,"
        "c.reason_code,c.reason,s.source_id,s.document_id,s.document_version_id,s.section_id,"
        "s.evidence_id,s.support_quote,s.quote_start,s.quote_end,s.evidence_sha256 "
        "FROM wiki_page_claims c JOIN wiki_page_revisions r ON r.source_scope=c.source_scope "
        "AND r.owner_id=c.owner_id AND r.knowledge_base_id=c.knowledge_base_id "
        "AND r.revision=c.revision AND r.page_id=c.page_id "
        "JOIN wiki_page_sources s ON s.source_scope=c.source_scope AND s.owner_id=c.owner_id "
        "AND s.knowledge_base_id=c.knowledge_base_id AND s.revision=c.revision "
        "AND s.page_id=c.page_id AND s.claim_id=c.claim_id WHERE c.source_scope=? "
        "AND c.owner_id=? AND c.knowledge_base_id=? AND c.revision=? "
        "ORDER BY r.title,c.section_heading,c.claim_id,s.source_id", context,
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(row["claim_id"], {
            "page_id": row["page_id"], "page_title": row["title"], "page_type": row["page_type"],
            "section_heading": row["section_heading"], "claim_id": row["claim_id"],
            "claim_text": row["claim_text"], "ai_verdict": row["verdict"],
            "ai_reason_code": row["reason_code"], "ai_reason": row["reason"],
            "sources": [], "human_supported": "", "human_issue_type": "", "human_notes": "",
        })
        item["sources"].append({key: row[key] for key in (
            "source_id", "document_id", "document_version_id", "section_id", "evidence_id",
            "support_quote", "quote_start", "quote_end", "evidence_sha256",
        )})
    return [{
        **{key: value for key, value in item.items() if key != "sources"},
        "sources_json": json.dumps(item["sources"], ensure_ascii=False),
    } for item in grouped.values()]


def _write_candidates(path: Path, candidates: list[dict[str, Any]]) -> None:
    rows = [{
        "candidate_id": item["id"], "kind": item["kind"], "category": item.get("category"),
        "name": item["name"], "aliases_json": json.dumps(item.get("aliases") or [], ensure_ascii=False),
        "description": item.get("description", ""), "status": item["status"],
        "promotion_status": item.get("promotion_status", "PENDING"),
        "promotion_reason": item.get("promotion_reason", ""),
        "document_ids_json": json.dumps(item.get("document_ids") or [], ensure_ascii=False),
        "sources_json": json.dumps(item.get("sources") or [], ensure_ascii=False),
        "human_candidate_valid": "", "human_type_valid": "", "human_promotion_valid": "",
        "human_notes": "",
    } for item in candidates]
    _write_csv(path, rows)


def _write_identities(
    path: Path, identities: list[dict[str, Any]], conflicts: set[str],
) -> None:
    rows = [{
        "identity_id": item["identity_id"], "kind": item["kind"], "category": item["category"],
        "canonical_name": item["canonical_name"], "slug": item["slug"],
        "aliases_json": json.dumps(_identity_aliases(item), ensure_ascii=False),
        "candidate_ids_json": item["candidate_ids"], "source_ids_json": item["source_ids"],
        "cross_kind_name_conflict": item["identity_id"] in conflicts,
        "human_identity_valid": "", "human_merge_valid": "", "human_notes": "",
    } for item in identities]
    _write_csv(path, rows)


def _identity_aliases(item: dict[str, Any]) -> list[str]:
    return list(item.get("aliases") or [])


def _write_pages(path: Path, pages: list[dict[str, Any]]) -> None:
    rows = []
    for item in pages:
        payload = json.loads(item["payload"])
        rows.append({
            "page_id": item["page_id"], "page_type": item["page_type"], "title": item["title"],
            "slug": item["slug"], "identity_id": item["identity_id"], "status": item["status"],
            "summary": item["summary"],
            "claim_count": sum(len(section["claims"]) for section in payload.get("sections") or []),
            "link_count": len(payload.get("links") or []),
            "human_page_worthy": "", "human_summary_supported": "", "human_notes": "",
        })
    _write_csv(path, rows)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    fields = list(values[0]) if values else ["empty"]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def _json_fields(row: dict[str, Any], *fields: str) -> dict[str, Any]:
    return {
        key: json.dumps(value, ensure_ascii=False) if key in fields and not isinstance(value, str) else value
        for key, value in row.items()
    }


def _cross_kind_identity_conflicts(identities: list[dict[str, Any]]) -> set[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in identities:
        grouped[_normalize(item["canonical_name"])].append(item)
    return {
        item["identity_id"] for group in grouped.values()
        if len({item["kind"] for item in group}) > 1 for item in group
    }


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w\u4e00-\u9fff]+", " ", value).split())


def _stats(run, candidates, identities, pages, claims, audits, repairs, conflicts) -> dict[str, Any]:
    return {
        "evaluation_label": "PROBE", "revision": run["revision"], "status": run["status"],
        "citation_authority": False,
        "candidates": len(candidates),
        "candidate_status": dict(Counter(item["status"] for item in candidates)),
        "promotion_status": dict(Counter(item.get("promotion_status", "PENDING") for item in candidates)),
        "identities": len(identities), "identity_kind": dict(Counter(item["kind"] for item in identities)),
        "cross_kind_name_conflict_identities": len(conflicts),
        "pages": len(pages), "page_type": dict(Counter(item["page_type"] for item in pages)),
        "final_claims": len(claims), "audit_events": len(audits),
        "audit_verdicts": dict(Counter(item["verdict"] for item in audits)),
        "repair_events": len(repairs), "repair_actions": dict(Counter(item["action"] for item in repairs)),
        "human_review": "NOT_RUN", "formal_retrieval_evaluation": "NOT_RUN",
    }


def _readme(revision: str) -> str:
    return f"""# Wiki review bundle\n\nRevision: `{revision}`\n\nThis is a private PROBE artifact. It is not publication approval.\n\nReview order:\n\n1. `01-candidates.csv`: validate candidate, type, Evidence binding, and promotion decision.\n2. `02-identities.csv`: validate canonical identity and merges; inspect cross-kind conflicts.\n3. `03-pages.csv`: decide whether each generated page is useful and grounded.\n4. `04-final-claims.csv`: verify every final claim against all listed exact Evidence excerpts.\n5. `05-audit-events.csv` and `06-repair-events.csv`: inspect the complete AI audit and repair chain.\n6. `07-pages.json`: inspect complete Wiki page structure and links.\n\nOnly fill columns prefixed with `human_`. AI output must not be presented as human approval.\n"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
