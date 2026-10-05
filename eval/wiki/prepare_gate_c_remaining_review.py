"""Prepare the two missing human Gate C metric sheets from a frozen bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite review packet: {args.output_dir}")
    bundle_manifest = json.loads((args.bundle / "manifest.json").read_text(encoding="utf-8"))
    paths = {name: args.bundle / f"{name}.csv" for name in
             ("01-candidates", "03-pages", "04-final-claims")}
    for name, path in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != bundle_manifest["files"][path.name]:
            raise ValueError(f"frozen bundle changed: {name}")
    candidates = _rows(paths["01-candidates"])
    pages = _rows(paths["03-pages"])
    claims = _rows(paths["04-final-claims"])
    args.output_dir.mkdir(parents=True)

    page_rows = [{
        "page_id": row["page_id"], "page_type": row["page_type"], "title": row["title"],
        "status": row["status"], "summary": row["summary"],
        "claim_count": row["claim_count"],
        "human_duplicate_of": "", "human_duplicate_notes": "",
    } for row in pages]
    _write(args.output_dir / "page-duplicate-review.csv", page_rows)

    locations: dict[tuple, dict] = {}
    for items in (candidates, claims):
        for row in items:
            for source in json.loads(row["sources_json"]):
                key = tuple(source[field] for field in (
                    "document_id", "document_version_id", "evidence_id", "section_id",
                    "quote_start", "quote_end", "evidence_sha256", "support_quote",
                ))
                if key not in locations:
                    locations[key] = {
                        "location_id": hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20],
                        "document_id": source["document_id"],
                        "document_version_id": source["document_version_id"],
                        "evidence_id": source["evidence_id"], "section_id": source["section_id"],
                        "quote_start": source["quote_start"], "quote_end": source["quote_end"],
                        "evidence_sha256": source["evidence_sha256"],
                        "support_quote": source["support_quote"],
                        "binding_count": 0, "human_location_valid": "", "human_location_notes": "",
                    }
                locations[key]["binding_count"] += 1
    location_rows = sorted(locations.values(), key=lambda item: item["location_id"])
    _write(args.output_dir / "evidence-location-review.csv", location_rows)

    report = {
        "status": "AWAITING_HUMAN_REVIEW", "gate_c": "PARTIAL",
        "revision": bundle_manifest["revision"],
        "source_table_sha256": {name: bundle_manifest["files"][path.name] for name, path in paths.items()},
        "pages_to_check_for_semantic_duplicates": len(page_rows),
        "unique_evidence_locations_to_check": len(location_rows),
        "source_bindings_covered": sum(row["binding_count"] for row in location_rows),
        "page_ids": [row["page_id"] for row in page_rows],
        "location_ids": [row["location_id"] for row in location_rows],
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "README.md").write_text(
        "# Remaining Gate C human metrics\n\n"
        "For every page, enter `NONE` or another listed page ID in `human_duplicate_of` "
        "and explain suspected duplicates in `human_duplicate_notes`. Compute semantic duplicate rate "
        "over the frozen 75-page population; page worthiness is a separate judgment.\n\n"
        "For every distinct Evidence location, compare the quote, document version, evidence ID, "
        "offset and hash with the original Confluence source. Enter TRUE/FALSE in "
        "`human_location_valid` and a source-based note. One row may cover multiple bindings; "
        "the binding count is shown. These sheets are unreviewed until filled by a human.\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in (
        "status", "pages_to_check_for_semantic_duplicates",
        "unique_evidence_locations_to_check", "source_bindings_covered",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
