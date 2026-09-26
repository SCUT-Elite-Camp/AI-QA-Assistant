"""Prepare a reproducible human Claim review sample from a private Wiki bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sample(rows: list[dict[str, str]], count: int, seed: str) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["page_type"]].append(row)
    if count > len(rows) or count < 1:
        raise ValueError("sample size must be between 1 and the number of Claims")
    quota = {kind: count * len(group) // len(rows) for kind, group in groups.items()}
    remaining = count - sum(quota.values())
    for kind in sorted(groups, key=lambda item: (-(count * len(groups[item]) % len(rows)), item))[:remaining]:
        quota[kind] += 1
    selected = []
    for kind, group in groups.items():
        ranked = sorted(group, key=lambda row: _sha256(f"{seed}:{row['claim_id']}".encode("utf-8")))
        selected.extend(ranked[:quota[kind]])
    return sorted(selected, key=lambda row: (row["page_type"], row["page_title"], row["claim_id"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite review sample: {args.output_dir}")
    source = args.bundle / "04-final-claims.csv"
    source_bytes = source.read_bytes()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    revision = json.loads((args.bundle / "stats.json").read_text(encoding="utf-8"))["revision"]
    seed = f"gate-c-v1:{revision}:{_sha256(source_bytes)}"
    selected = _sample(rows, args.count, seed)
    args.output_dir.mkdir(parents=True)
    fields = [
        "page_type", "page_title", "section_heading", "claim_id", "claim_text",
        "source_count", "source_quotes_json", "source_references_json",
        "automated_audit_verdict", "human_supported", "human_issue_type", "human_notes",
    ]
    with (args.output_dir / "claim-review-100.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            sources = json.loads(row["sources_json"])
            writer.writerow({
                "page_type": row["page_type"], "page_title": row["page_title"],
                "section_heading": row["section_heading"], "claim_id": row["claim_id"],
                "claim_text": row["claim_text"], "source_count": len(sources),
                "source_quotes_json": json.dumps([source["support_quote"] for source in sources], ensure_ascii=False),
                "source_references_json": json.dumps([{key: value for key, value in source.items()
                    if key != "support_quote"} for source in sources], ensure_ascii=False),
                "automated_audit_verdict": row["ai_verdict"],
                "human_supported": "", "human_issue_type": "", "human_notes": "",
            })
    manifest = {
        "status": "AWAITING_HUMAN_REVIEW", "gate_c": "NOT_RUN", "revision": revision,
        "source_claims_sha256": _sha256(source_bytes), "sampling_seed": seed,
        "population": len(rows), "sample_size": len(selected),
        "sample_by_page_type": dict(Counter(row["page_type"] for row in selected)),
        "selected_claim_ids": [row["claim_id"] for row in selected],
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    review_record = {
        "revision": revision,
        "sample_sha256": _sha256((args.output_dir / "claim-review-100.csv").read_bytes()),
        "human_reviewer": "",
        "reviewed_at_utc": "",
        "reviewed_claims": 0,
        "gate_c": "NOT_RUN",
    }
    (args.output_dir / "review-record-template.json").write_text(
        json.dumps(review_record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (args.output_dir / "README.md").write_text(
        "# Gate C human Claim review\n\n"
        f"The sample is deterministic and stratified by Wiki page type. The original {len(rows)}-Claim "
        "bundle remains the source of truth. Review each Claim against every listed original "
        "Evidence quote. Enter `yes` or `no` in `human_supported`, an issue type in "
        "`human_issue_type` (`NONE` when supported), and the source-based rationale in "
        "`human_notes`. Copy `review-record-template.json` to a review record and fill the "
        "human reviewer, time, and completed count only after reviewing the rows. "
        "The automated verdict is context "
        "only and cannot count as human approval. Candidate precision, identity merges, duplicate "
        "pages, and exact Evidence location also need separate human checks using the full bundle. "
        "Gate C stays NOT_RUN until those checks are completed and scored.\n",
        encoding="utf-8",
    )
    print(json.dumps({key: manifest[key] for key in ("status", "population", "sample_size", "sample_by_page_type")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
