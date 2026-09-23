"""Compare two complete AI reviews and produce a source-linked review queue.

The queue is AI assistance only; it never writes human fields or Gate C PASS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


FILES = {
    "claim": ("04-final-claims.csv", "claim_id"),
    "candidate": ("01-candidates.csv", "candidate_id"),
    "identity": ("02-identities.csv", "identity_id"),
    "page": ("03-pages.csv", "page_id"),
}


def _csv(path: Path, key: str) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        values = list(csv.DictReader(handle))
    result = {value[key]: value for value in values}
    if len(result) != len(values):
        raise ValueError(f"duplicate {key} in {path}")
    return result


def _review(path: Path) -> dict[str, dict]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    result = {value["id"]: value for value in values}
    if len(result) != len(values) or any(value.get("reviewer_kind") != "AI" for value in values):
        raise ValueError(f"invalid AI review file: {path}")
    return result


def _negative(category: str, row: dict, review: dict) -> bool:
    if category == "claim":
        return not review["supported"]
    if category == "candidate":
        return (not review["valid"] or not review["type_valid"]
                or row["promotion_status"] == "PROMOTED" and not review["promotion_valid"])
    if category == "identity":
        return not review["merge_valid"] or not review["kind_valid"]
    return not review["worthy"] or not review["summary_supported"] or bool(review["duplicate_of"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--flash", type=Path, required=True)
    parser.add_argument("--pro", type=Path, required=True)
    parser.add_argument("--pro-identity", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite review queue: {args.output}")
    inputs = {}
    queue = []
    metrics = {}
    for category, (filename, key) in FILES.items():
        source_path = args.bundle / filename
        flash_path = args.flash / f"{category}-reviews.jsonl"
        pro_path = (args.pro_identity if category == "identity" and args.pro_identity
                    else args.pro) / f"{category}-reviews.jsonl"
        rows = _csv(source_path, key)
        flash = _review(flash_path)
        pro = _review(pro_path)
        if set(rows) != set(flash) or set(rows) != set(pro):
            raise ValueError(f"incomplete or mismatched {category} AI reviews")
        inputs[category] = {
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "flash_sha256": hashlib.sha256(flash_path.read_bytes()).hexdigest(),
            "pro_sha256": hashlib.sha256(pro_path.read_bytes()).hexdigest(),
        }
        counts = {"population": len(rows), "flash_flagged": 0, "pro_flagged": 0,
                  "both_flagged": 0, "disagreed": 0}
        for item_id, row in rows.items():
            first = _negative(category, row, flash[item_id])
            second = _negative(category, row, pro[item_id])
            counts["flash_flagged"] += first
            counts["pro_flagged"] += second
            counts["both_flagged"] += first and second
            counts["disagreed"] += first != second
            if not first and not second:
                continue
            queue.append({
                "category": category, "id": item_id,
                "priority": "BOTH_AI_FLAGGED" if first and second else "AI_DISAGREEMENT",
                "source_record": row,
                "flash_review": flash[item_id], "pro_review": pro[item_id],
            })
        metrics[category] = counts
    queue.sort(key=lambda item: (item["priority"] != "BOTH_AI_FLAGGED",
                                      item["category"], item["id"]))
    report = {
        "evaluation_label": "AI_ONLY_REVIEW_QUEUE",
        "status": "PASS", "gate_c": "NOT_RUN", "human_review": "NOT_RUN",
        "inputs": inputs, "metrics": metrics,
        "queue_size": len(queue), "queue": queue,
        "interpretation": "AI disagreements require source review; neither model is a human adjudicator.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"queue_size": len(queue), "metrics": metrics,
                      "gate_c": "NOT_RUN"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
