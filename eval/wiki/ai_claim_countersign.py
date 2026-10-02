"""Run a separately labelled AI Claim review; never populate human Gate C fields."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data-pipeline"))

from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment  # noqa: E402


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"}, "supported": {"type": "boolean"},
            "issue_type": {"type": "string", "enum": [
                "NONE", "UNSUPPORTED", "OVERSTATED", "WRONG_ENTITY", "WRONG_TIME",
                "MISSING_CONTEXT", "AMBIGUOUS", "OTHER",
            ]},
            "reason": {"type": "string"},
        }, "required": ["claim_id", "supported", "issue_type", "reason"],
    }}}, "required": ["reviews"],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 10:
        raise ValueError("batch size must be between 1 and 10")
    sample = args.sample_dir / "claim-review-100.csv"
    sample_hash = hashlib.sha256(sample.read_bytes()).hexdigest()
    with sample.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads((args.sample_dir / "manifest.json").read_text(encoding="utf-8"))
    if [row["claim_id"] for row in rows] != manifest["selected_claim_ids"]:
        raise ValueError("sample rows differ from the frozen manifest")
    output = args.sample_dir / "ai-review.jsonl"
    summary_path = args.sample_dir / "ai-review-summary.json"
    prior_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    reviewed = {}
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["sample_sha256"] != sample_hash:
                raise ValueError("AI review belongs to a different sample")
            reviewed[item["claim_id"]] = item
    client = DeepSeekJsonLLM(api_key=deepseek_api_key_from_environment())
    remaining = [row for row in rows if row["claim_id"] not in reviewed]
    for offset in range(0, len(remaining), args.batch_size):
        batch = remaining[offset:offset + args.batch_size]
        prompt_rows = [{
            "claim_id": row["claim_id"], "page_title": row["page_title"],
            "claim_text": row["claim_text"],
            "evidence_quotes": json.loads(row["source_quotes_json"]),
        } for row in batch]
        response = client.complete(
            system=(
                "Independently judge whether each Chinese Wiki claim follows from its supplied original "
                "Evidence quotes. Interpret English evidence accurately. Check names, dates, quantifiers, "
                "attribution, and whether a claim is stronger than the evidence. Treat prior automated "
                "verdicts as unavailable. If support is uncertain, mark unsupported and explain. "
                "Return one concise review for every claim_id. This is AI review, not human approval."
            ),
            user={"claims": prompt_rows}, schema_name="wiki_independent_ai_claim_review_v1",
            schema=SCHEMA, max_tokens=2500,
        )
        values = response.get("reviews")
        expected = {row["claim_id"] for row in batch}
        if not isinstance(values, list) or len(values) != len(batch) or {item.get("claim_id") for item in values} != expected:
            raise ValueError("AI review returned incomplete or mismatched Claim IDs")
        for item in values:
            if not isinstance(item.get("supported"), bool) or item.get("issue_type") not in SCHEMA["properties"]["reviews"]["items"]["properties"]["issue_type"]["enum"] or not str(item.get("reason", "")).strip():
                raise ValueError("AI review returned an invalid verdict")
            item.update({
                "reviewer_kind": "AI", "reviewer_model": client.model,
                "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
                "sample_sha256": sample_hash,
            })
        with output.open("a", encoding="utf-8") as handle:
            for item in values:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"AI reviewed {len(reviewed) + offset + len(batch)}/{len(rows)}", flush=True)
    completed = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    if len(completed) != len(rows) or {item["claim_id"] for item in completed} != {row["claim_id"] for row in rows}:
        raise ValueError("AI review is not complete")
    result = {
        "signed_by": "Codex (AI)", "signed_at_utc": datetime.now(timezone.utc).isoformat(),
        "attestation": "AI-only countersign of the sampled Claim-to-Evidence review",
        "reviewer_kind": "AI", "reviewer_model": client.model,
        "claim_sample_size": len(rows), "ai_supported": sum(item["supported"] for item in completed),
        "ai_unsupported": sum(not item["supported"] for item in completed),
        "sample_sha256": sample_hash, "source_claims_sha256": manifest["source_claims_sha256"],
        "gate_c": "NOT_RUN", "human_review": "NOT_RUN", "published": False,
        "usage_this_run": client.usage,
        "usage_total": {
            key: int((prior_summary.get("usage_total") or prior_summary.get("usage_this_run") or {}).get(key, 0)) + value
            for key, value in client.usage.items()
        },
    }
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
