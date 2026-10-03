"""Resumable AI-only semantic review of the complete frozen Wiki bundle.

The output never populates human review columns or grants Gate C approval.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data-pipeline"))
from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment  # noqa: E402


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_for(category: str) -> dict:
    fields = {
        "claim": {"supported": {"type": "boolean"}, "issue_type": {"type": "string"}},
        "candidate": {"valid": {"type": "boolean"}, "type_valid": {"type": "boolean"},
                      "promotion_valid": {"type": "boolean"}},
        "identity": {"merge_valid": {"type": "boolean"}, "kind_valid": {"type": "boolean"}},
        "page": {"worthy": {"type": "boolean"}, "summary_supported": {"type": "boolean"},
                 "duplicate_of": {"type": "string"}},
    }[category]
    properties = {"id": {"type": "string"}, **fields, "reason": {"type": "string"}}
    return {"type": "object", "additionalProperties": False,
            "properties": {"reviews": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": properties, "required": list(properties),
            }}}, "required": ["reviews"]}


def build_items(bundle: Path) -> dict[str, list[dict]]:
    candidates = rows(bundle / "01-candidates.csv")
    identities = rows(bundle / "02-identities.csv")
    pages = rows(bundle / "03-pages.csv")
    claims = rows(bundle / "04-final-claims.csv")
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    claims_by_page: dict[str, list[dict]] = defaultdict(list)
    for claim in claims:
        claims_by_page[claim["page_id"]].append(claim)

    result = {
        "claim": [{
            "id": item["claim_id"], "page_title": item["page_title"],
            "claim": item["claim_text"],
            "evidence_quotes": [value["support_quote"] for value in json.loads(item["sources_json"])],
        } for item in claims],
        "candidate": [{
            "id": item["candidate_id"], "kind": item["kind"],
            "name": item["name"], "description": item["description"],
            "promotion_status": item["promotion_status"],
            "evidence_quotes": [value["support_quote"] for value in json.loads(item["sources_json"])],
        } for item in candidates],
        "identity": [{
            "id": item["identity_id"], "kind": item["kind"],
            "canonical_name": item["canonical_name"],
            "members": [{"name": candidates_by_id[member]["name"],
                         "description": candidates_by_id[member]["description"],
                         "evidence_quotes": [source["support_quote"] for source in json.loads(
                             candidates_by_id[member]["sources_json"
                             ])]}
                        for member in json.loads(item["candidate_ids_json"])],
        } for item in identities],
        "page": [{
            "id": item["page_id"], "type": item["page_type"],
            "title": item["title"], "summary": item["summary"],
            "claims": [claim["claim_text"] for claim in claims_by_page[item["page_id"]]],
        } for item in pages],
    }
    return result


def review_batch(category: str, batch: list[dict], all_pages: list[dict], model: str) -> tuple[list[dict], dict]:
    client = DeepSeekJsonLLM(api_key=deepseek_api_key_from_environment(), model=model)
    instruction = {
        "claim": "Judge whether every claim is fully entailed by all supplied original Evidence quotes. Check entity, time, quantifier, attribution, and missing context. If uncertain, supported=false. issue_type is NONE only when supported, otherwise explain the defect. Do not trust prior AI verdicts.",
        "candidate": "Judge whether each extracted concept/entity candidate accurately represents its original Evidence, whether its kind is correct, and whether promotion to a reusable Wiki object is warranted. Do not infer facts absent from quotes.",
        "identity": "Judge whether all member candidates refer to the same real concept/entity without merging different people, teams, events, or concepts. Check canonical kind. Member descriptions are secondary context, not original source proof; mark uncertain merges invalid.",
        "page": "Judge whether the page is a meaningful distinct Wiki page, whether its summary is supported by its listed claims, and whether it semantically duplicates another page in the supplied catalog. duplicate_of must be an existing page ID or empty string. For INDEX pages with no claims, judge summary conservatively.",
    }[category]
    catalog = [{"id": item["id"], "type": item["type"], "title": item["title"]}
               for item in all_pages] if category == "page" else None
    expected = {item["id"] for item in batch}
    reviews = None
    for _attempt in range(3):
        try:
            output = client.complete(
                system=("Independent AI audit, not human approval. " + instruction
                        + " Return exactly one concise review per supplied ID, with no extra IDs. "
                        "All boolean judgments must be conservative."),
                user={"items": batch, "required_ids": sorted(expected),
                      **({"page_catalog": catalog} if catalog is not None else {})},
                schema_name=f"wiki_ai_{category}_review_v1", schema=schema_for(category),
                max_tokens=3200,
            )
        except ValueError as exc:
            if "did not finish normally: length" not in str(exc) or len(batch) < 2:
                raise
            midpoint = len(batch) // 2
            first, first_usage = review_batch(category, batch[:midpoint], all_pages, model)
            second, second_usage = review_batch(category, batch[midpoint:], all_pages, model)
            return first + second, dict(Counter(client.usage) + Counter(first_usage) + Counter(second_usage))
        reviews = output.get("reviews")
        if (isinstance(reviews, list) and len(reviews) == len(batch)
                and {item.get("id") for item in reviews} == expected):
            break
    else:
        raise ValueError(f"incomplete {category} AI review batch: {sorted(expected)}")
    fields = [key for key in schema_for(category)["properties"]["reviews"]["items"]["properties"]
              if key not in {"id", "reason", "issue_type", "duplicate_of"}]
    page_ids = {item["id"] for item in all_pages}
    for item in reviews:
        if not str(item.get("reason") or "").strip() or any(
            not isinstance(item.get(field), bool) for field in fields
        ):
            raise ValueError(f"invalid {category} AI verdict")
        if category == "page" and item.get("duplicate_of") not in page_ids | {""}:
            raise ValueError("AI duplicate_of is not a known page")
        item.update({"category": category, "reviewer_kind": "AI",
                     "reviewer_model": model,
                     "reviewed_at_utc": datetime.now(timezone.utc).isoformat()})
    return reviews, client.usage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", choices=("deepseek-v4-pro", "deepseek-v4-flash"),
                        default="deepseek-v4-flash")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--category", choices=("claim", "candidate", "identity", "page", "all"),
                        default="all")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    items = build_items(args.bundle)
    source_hashes = {name: sha256(args.bundle / filename) for name, filename in (
        ("candidate", "01-candidates.csv"), ("identity", "02-identities.csv"),
        ("page", "03-pages.csv"), ("claim", "04-final-claims.csv"),
    )}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    manifest = {"source_hashes": source_hashes, "reviewer_kind": "AI",
                "reviewer_model": args.model, "gate_c": "NOT_RUN", "human_review": "NOT_RUN"}
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("AI review inputs or model changed; choose a new output directory")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    batch_size = {"claim": 8, "candidate": 4, "identity": 6, "page": 3}
    selected = list(items) if args.category == "all" else [args.category]
    for category in selected:
        output = args.output_dir / f"{category}-reviews.jsonl"
        completed = {}
        if output.exists():
            for line in output.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if item["id"] in completed:
                    raise ValueError("duplicate AI review ID")
                completed[item["id"]] = item
        remaining = [item for item in items[category] if item["id"] not in completed]
        batches = [remaining[index:index + batch_size[category]]
                   for index in range(0, len(remaining), batch_size[category])]
        usage = Counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(review_batch, category, batch, items["page"], args.model): batch
                       for batch in batches}
            for future in as_completed(futures):
                reviews, call_usage = future.result()
                with output.open("a", encoding="utf-8") as handle:
                    for review in reviews:
                        handle.write(json.dumps(review, ensure_ascii=False) + "\n")
                        completed[review["id"]] = review
                usage.update(call_usage)
                print(f"{category}: {len(completed)}/{len(items[category])}", flush=True)
        report = {"category": category, "reviewer_kind": "AI", "gate_c": "NOT_RUN",
                  "status": "PASS" if len(completed) == len(items[category]) else "PARTIAL",
                  "population": len(items[category]), "reviewed": len(completed),
                  "negative_verdicts": sum(any(
                      value is False for key, value in review.items()
                      if key in {"supported", "valid", "type_valid", "promotion_valid",
                                 "merge_valid", "kind_valid", "worthy", "summary_supported"}
                  ) or bool(review.get("duplicate_of")) for review in completed.values()),
                  "usage_this_run": dict(usage)}
        (args.output_dir / f"{category}-summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
