"""Audit one frozen, unpublished Wiki PROBE against the Gate B contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from pipeline.wiki.domain import WikiIdentity, WikiPageDraft, WikiPageType  # noqa: E402
from pipeline.wiki.finalize import finalize_wiki_pages  # noqa: E402


def audit(run_dir: Path, cohort_path: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads((Path(__file__).parent / "baselines" /
                           "wiki-refactor-meeting-12-pre-handle-20260915.json").read_text(encoding="utf-8"))
    cohort_hash = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    revision = manifest["result"]["revision"]
    with sqlite3.connect(run_dir / "wiki.sqlite3") as db:
        db.row_factory = sqlite3.Row
        rows = lambda table: db.execute(
            f"SELECT * FROM {table} WHERE revision=?", (revision,),
        ).fetchall()
        candidates = rows("wiki_candidate_sources")
        sources = rows("wiki_page_sources")
        claims = rows("wiki_page_claims")
        audits = rows("wiki_claim_audits")
        issues = rows("wiki_page_issues")
        pages = [WikiPageDraft.model_validate(json.loads(row["payload"]))
                 for row in rows("wiki_page_revisions")]
        identities = []
        for row in rows("wiki_identities"):
            aliases = [item["alias"] for item in db.execute(
                "SELECT alias FROM wiki_identity_aliases WHERE revision=? AND identity_id=?",
                (revision, row["identity_id"]),
            )]
            identities.append(WikiIdentity.model_validate({
                "id": row["identity_id"], "kind": row["kind"],
                "scope": {"source_scope": row["source_scope"], "owner_id": row["owner_id"],
                          "knowledge_base_id": row["knowledge_base_id"]},
                "canonical_name": row["canonical_name"], "slug": row["slug"],
                "category": row["category"], "aliases": aliases,
                "candidate_ids": json.loads(row["candidate_ids"]),
                "source_ids": json.loads(row["source_ids"]),
                "description": row["description"],
            }))

    def valid_source(row: sqlite3.Row) -> bool:
        quote = row["support_quote"]
        return (row["quote_start"] == 0 and row["quote_end"] == len(quote)
                and hashlib.sha256(quote.encode("utf-8")).hexdigest() == row["evidence_sha256"])

    by_source: dict[tuple[str, str], set[str]] = {}
    by_audit: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in sources:
        by_source.setdefault((row["page_id"], row["claim_id"]), set()).add(row["source_id"])
    for row in audits:
        by_audit.setdefault((row["page_id"], row["claim_id"]), []).append(row)
    exact = sum(any(
        event["claim_text"] == claim["claim_text"]
        and set(json.loads(event["source_ids"])) == by_source.get((claim["page_id"], claim["claim_id"]), set())
        and event["verdict"] == "SUPPORTED" and event["reason_code"] == "ENTAILED"
        for event in by_audit.get((claim["page_id"], claim["claim_id"]), [])
    ) for claim in claims)
    page_ids = {page.id for page in pages}
    slugs = {page.slug for page in pages}
    dead = sum(bool(set(page.links) - page_ids) or any(
        slug not in slugs for slug in re.findall(r"\]\(/wiki/([^\)]+)\)",
            "\n".join([page.summary, *(claim.rendered_text for section in page.sections
                                      for claim in section.claims)]))
    ) for page in pages)
    finalized = {page.id: page for page in finalize_wiki_pages(pages, identities)}
    unlinked = sum(page.page_type == WikiPageType.SUMMARY and finalized[page.id] != page
                   for page in pages)
    non_chinese = sum(len(page.summary.strip()) > 20
                      and not re.search(r"[\u4e00-\u9fff]", page.summary)
                      for page in pages if page.page_type != WikiPageType.INDEX)
    non_chinese_claims = sum(len(claim["claim_text"]) > 20
                             and not re.search(r"[\u4e00-\u9fff]", claim["claim_text"])
                             for claim in claims)
    quarantined = {issue["target_id"] for issue in issues
                   if issue["code"] == "TYPE_CONFLICT_UNRESOLVED"}
    included = set().union(*(set(identity.candidate_ids) for identity in identities)) if identities else set()
    checks = {
        "frozen_cohort": cohort_hash == manifest["cohort_sha256"]
                         == baseline["cohort_sha256"] and manifest["source_pages"] == 12,
        "invalid_evidence_bindings_zero": not any(issue["code"] == "INVALID_EVIDENCE_BINDING" for issue in issues),
        "evidence_hash_offset_coverage": all(map(valid_source, [*candidates, *sources])),
        "exact_supported_claim_audits": exact == len(claims),
        "unresolved_type_conflicts_excluded": not quarantined.intersection(included),
        "dead_links_zero": dead == 0,
        "unlinked_summary_targets_zero": unlinked == 0,
        "chinese_prose_consistency": non_chinese == 0 and non_chinese_claims == 0,
        "identical_rerun_zero_api_calls": manifest["completion_cache"]["misses"] == 0
                                     and manifest["token_usage"]["total_tokens"] == 0
                                     and (manifest.get("confirmation_token_usage") or {}).get(
                                         "total_tokens", 0) == 0,
        "unpublished_probe": not manifest["result"]["published"],
    }
    return {
        "evaluation_label": "PROBE", "status": "PASS" if all(checks.values()) else "PARTIAL",
        "revision": revision, "cohort_sha256": cohort_hash, "checks": checks,
        "before": {"candidates": baseline["metrics"]["candidates"],
                   "identities": baseline["metrics"]["identities"],
                   "pages": baseline["metrics"]["pages"],
                   "invalid_evidence_bindings": baseline["metrics"]["invalid_evidence_bindings"]},
        "after": {"candidates": manifest["result"]["candidates"],
                  "identities": manifest["result"]["identities"],
                  "pages": len(pages),
                  "invalid_evidence_bindings": sum(issue["code"] == "INVALID_EVIDENCE_BINDING"
                                                   for issue in issues)},
        "counts": {"candidate_sources": len(candidates), "page_sources": len(sources),
                   "final_claims": len(claims), "exact_supported_audits": exact,
                   "dead_link_pages": dead, "unlinked_summary_pages": unlinked,
                   "non_chinese_summary_pages": non_chinese,
                   "non_chinese_claims": non_chinese_claims,
                   "quarantined_conflicts": len(quarantined),
                   "rerun_cache_hits": manifest["completion_cache"]["hits"],
                   "rerun_api_misses": manifest["completion_cache"]["misses"]},
        "human_review": "NOT_RUN", "formal_retrieval_evaluation": "NOT_RUN",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("cohort", type=Path)
    args = parser.parse_args()
    report = audit(args.run_dir, args.cohort)
    (args.run_dir / "gate-b-current.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
