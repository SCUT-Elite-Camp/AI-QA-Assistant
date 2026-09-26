"""Check a submitted full Wiki review bundle against its frozen source tables."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile


TABLES = (
    "01-candidates", "02-identities", "03-pages", "04-final-claims",
    "05-audit-events", "06-repair-events",
)
VERDICT_COLUMNS = {
    "01-candidates": ("human_candidate_valid", "human_type_valid", "human_promotion_valid"),
    "02-identities": ("human_identity_valid", "human_merge_valid"),
    "03-pages": ("human_page_worthy", "human_summary_supported"),
    "04-final-claims": ("human_supported",),
    "05-audit-events": ("human_event_valid",),
    "06-repair-events": ("human_repair_valid",),
}


def _read_csv(handle) -> tuple[list[str], list[dict[str, str]]]:
    with io.TextIOWrapper(handle, encoding="utf-8-sig", newline="") as text:
        reader = csv.DictReader(text)
        return list(reader.fieldnames or []), list(reader)


def validate(bundle: Path, archive: Path) -> dict:
    stats = json.loads((bundle / "stats.json").read_text(encoding="utf-8"))
    bundle_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if bundle_manifest["revision"] != stats["revision"]:
        raise ValueError("bundle revision differs from its manifest")
    expected_names = {f"{name}-human-reviewed.csv" for name in TABLES} | {"review-summary.csv"}
    tables: dict[str, list[dict[str, str]]] = {}
    counts: dict[str, dict[str, dict[str, int]]] = {}
    original_hashes: dict[str, str] = {}
    with zipfile.ZipFile(archive) as zipped:
        files = zipped.infolist()
        if len(files) != len(expected_names) or {entry.filename for entry in files} != expected_names:
            raise ValueError("review archive has missing, duplicate, or unexpected files")
        if any(entry.flag_bits & 1 or entry.file_size > 10_000_000 for entry in files):
            raise ValueError("review archive contains encrypted or oversized entries")
        for name in TABLES:
            original_path = bundle / f"{name}.csv"
            original_hashes[name] = hashlib.sha256(original_path.read_bytes()).hexdigest()
            if original_hashes[name] != bundle_manifest["files"][f"{name}.csv"]:
                raise ValueError(f"frozen source table changed: {name}")
            with original_path.open("rb") as handle:
                original_fields, original = _read_csv(handle)
            with zipped.open(f"{name}-human-reviewed.csv") as handle:
                reviewed_fields, reviewed = _read_csv(handle)
            if len(reviewed) != len(original):
                raise ValueError(f"review row count differs: {name}")
            if reviewed_fields[:len(original_fields)] != original_fields:
                raise ValueError(f"frozen columns changed: {name}")
            new_fields = set(reviewed_fields) - set(original_fields)
            allowed = set(VERDICT_COLUMNS[name]) | {"human_notes"}
            if name == "04-final-claims":
                allowed.add("human_issue_type")
            if new_fields - allowed or set(VERDICT_COLUMNS[name]) - set(reviewed_fields):
                raise ValueError(f"invalid human review columns: {name}")
            for index, (source, result) in enumerate(zip(original, reviewed, strict=True), start=1):
                if any(source[field] != result[field] for field in original_fields
                       if not field.startswith("human_")):
                    raise ValueError(f"source row changed: {name}:{index}")
                if not result.get("human_notes", "").strip():
                    raise ValueError(f"missing review notes: {name}:{index}")
            tables[name] = reviewed
            counts[name] = {}
            for field in VERDICT_COLUMNS[name]:
                values = Counter(row[field].strip().upper() for row in reviewed)
                if set(values) - {"TRUE", "FALSE"}:
                    raise ValueError(f"incomplete verdicts: {name}:{field}")
                counts[name][field] = {"TRUE": values["TRUE"], "FALSE": values["FALSE"]}
        with zipped.open("review-summary.csv") as handle:
            _, summary_rows = _read_csv(handle)
    expected_summary = {
        (f"{name}-human-reviewed.csv", field): {**values, "other_or_blank": 0}
        for name, fields in counts.items() for field, values in fields.items()
    }
    expected_summary[("04-final-claims-human-reviewed.csv", "human_issue_type")] = {
        "TRUE": 0, "FALSE": 0, "other_or_blank": len(tables["04-final-claims"]),
    }
    if len(summary_rows) != len(expected_summary):
        raise ValueError("review summary has an incorrect number of rows")
    seen = set()
    for row in summary_rows:
        key = (row.get("file"), row.get("human_field"))
        if key not in expected_summary or key in seen:
            raise ValueError("review summary contains unknown or duplicate metric")
        seen.add(key)
        if (int(row["TRUE"]) != expected_summary[key]["TRUE"]
                or int(row["FALSE"]) != expected_summary[key]["FALSE"]
                or int(row["other_or_blank"]) != expected_summary[key]["other_or_blank"]):
            raise ValueError(f"review summary does not match rows: {key}")
    claim_rows = tables["04-final-claims"]
    for row in claim_rows:
        issue = row["human_issue_type"].strip()
        supported = row["human_supported"].strip().upper() == "TRUE"
        if (supported and issue not in {"", "NONE"}) or (not supported and issue in {"", "NONE"}):
            raise ValueError(f"inconsistent Claim issue type: {row['claim_id']}")
    claim_ids = {row["claim_id"] for row in claim_rows}
    invalid_claims = [row for row in claim_rows if row["human_supported"].upper() == "FALSE"]
    invalid_events = [row for row in tables["05-audit-events"]
                      if row["human_event_valid"].upper() == "FALSE"]
    if {row["claim_id"] for row in invalid_events} - claim_ids:
        raise ValueError("invalid audit event refers to an unknown final Claim")
    if len(claim_rows) != stats["final_claims"] or len(tables["01-candidates"]) != stats["candidates"]:
        raise ValueError("review tables do not match revision statistics")

    candidate_count = counts["01-candidates"]["human_candidate_valid"]["TRUE"]
    claim_count = counts["04-final-claims"]["human_supported"]["TRUE"]
    bad_merges = counts["02-identities"]["human_merge_valid"]["FALSE"]
    candidate_precision = candidate_count / len(tables["01-candidates"])
    claim_precision = claim_count / len(claim_rows)
    pages = {row["page_id"]: row for row in tables["03-pages"]}
    reviewing = {page_id for page_id, row in pages.items() if row["status"] == "REVIEWING"}
    return {
        "evaluation_label": "SUBMITTED_FULL_WIKI_REVIEW_CHECK",
        "status": "PARTIAL", "gate_c": "PARTIAL", "revision": stats["revision"],
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "original_table_sha256": original_hashes,
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "verdict_counts": counts,
        "candidate_precision": candidate_precision,
        "candidate_precision_90": "PASS" if candidate_precision >= 0.90 else "PARTIAL",
        "claim_support_precision": claim_precision,
        "claim_support_precision_95": "PASS" if claim_precision >= 0.95 else "PARTIAL",
        "identity_bad_merges": bad_merges,
        "identity_bad_merges_zero": "PASS" if bad_merges == 0 else "PARTIAL",
        "semantic_duplicate_page_rate": "NOT_RUN",
        "human_evidence_location_precision": "NOT_RUN",
        "rejected_claim_ids": [row["claim_id"] for row in invalid_claims],
        "invalid_audit_claim_ids": [row["claim_id"] for row in invalid_events],
        "invalid_claims_on_reviewing_pages": sum(row["page_id"] in reviewing for row in invalid_claims),
        "reviewing_pages_with_invalid_claims": sorted({row["page_id"] for row in invalid_claims
                                                       if row["page_id"] in reviewing}),
        "unworthy_reviewing_pages": sorted(page_id for page_id in reviewing
                                            if pages[page_id]["human_page_worthy"].upper() == "FALSE"),
        "unsupported_summary_reviewing_pages": sorted(page_id for page_id in reviewing
                                                        if pages[page_id]["human_summary_supported"].upper() == "FALSE"),
        "invalid_promoted_candidates": [row["candidate_id"] for row in tables["01-candidates"]
                                        if row["promotion_status"] == "PROMOTED"
                                        and row["human_promotion_valid"].upper() == "FALSE"],
        "invalid_repair_original_claim_ids": [row["original_claim_id"] for row in tables["06-repair-events"]
                                              if row["human_repair_valid"].upper() == "FALSE"],
        "limits": [
            "Page worthiness is not a semantic duplicate label",
            "No per-source human location verdict was submitted",
            "Submitted review marks final Claims and pages that require correction before publication",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite report: {args.output}")
    result = validate(args.bundle, args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "status", "gate_c", "row_counts", "candidate_precision", "claim_support_precision",
        "identity_bad_merges", "semantic_duplicate_page_rate", "human_evidence_location_precision",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
