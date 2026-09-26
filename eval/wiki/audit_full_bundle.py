"""Independent deterministic audit of a frozen Wiki review bundle.

This checks provenance and internal consistency for every item. Semantic
correctness and human Gate C approval are outside its authority.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline"):
    sys.path.insert(0, str(dependency))

from pipeline.confluence_snapshot import discover_confluence_snapshots  # noqa: E402
from pipeline.wiki.confluence_source import load_authoritative_confluence_document  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confluence-root", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite audit: {args.output}")

    cohort_bytes = args.cohort.read_bytes()
    cohort = json.loads(cohort_bytes.decode("utf-8-sig"))
    snapshots = {item.identity: item for item in discover_confluence_snapshots(
        args.confluence_root, require_storage=True,
    )}
    documents = {}
    evidence = {}
    for page in cohort["pages"]:
        snapshot = snapshots[tuple(page["identity"])]
        if (snapshot.content_sha256 != page["content_sha256"]
                or snapshot.source_content_sha256 != page["source_content_sha256"]):
            raise ValueError("frozen Confluence source changed")
        document = load_authoritative_confluence_document(snapshot)
        documents[document.doc_id] = document.version_id
        for chunk in document.chunks:
            evidence[(document.doc_id, document.version_id, chunk.chunk_id)] = chunk.text

    candidates = _rows(args.bundle / "01-candidates.csv")
    identities = _rows(args.bundle / "02-identities.csv")
    pages = _rows(args.bundle / "03-pages.csv")
    claims = _rows(args.bundle / "04-final-claims.csv")
    audits = _rows(args.bundle / "05-audit-events.csv")
    issues: list[dict[str, str]] = []
    checks = Counter()

    def issue(kind: str, item_id: str, code: str) -> None:
        issues.append({"kind": kind, "id": item_id, "code": code})

    def check_source(source: dict, kind: str, item_id: str) -> None:
        checks["source_bindings"] += 1
        doc_id = str(source.get("document_id") or "")
        version = str(source.get("document_version_id") or "")
        evidence_id = str(source.get("evidence_id") or "")
        text = evidence.get((doc_id, version, evidence_id))
        if text is None:
            issue(kind, item_id, "UNKNOWN_DOCUMENT_VERSION_OR_EVIDENCE")
            return
        if documents.get(doc_id) != version:
            issue(kind, item_id, "INACTIVE_SOURCE_VERSION")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != source.get("evidence_sha256"):
            issue(kind, item_id, "EVIDENCE_HASH_MISMATCH")
        start, end = int(source.get("quote_start", -1)), int(source.get("quote_end", -1))
        if start < 0 or end <= start or text[start:end] != source.get("support_quote"):
            issue(kind, item_id, "QUOTE_SPAN_MISMATCH")

    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    for row in candidates:
        for source in json.loads(row["sources_json"]):
            check_source(source, "candidate", row["candidate_id"])
    for row in identities:
        candidate_ids = json.loads(row["candidate_ids_json"])
        for candidate_id in candidate_ids:
            candidate = candidate_by_id.get(candidate_id)
            if candidate is None:
                issue("identity", row["identity_id"], "UNKNOWN_CANDIDATE")
            elif candidate["kind"] != row["kind"]:
                issue("identity", row["identity_id"], "CROSS_KIND_MERGE")

    supported_audits: dict[tuple[str, str], set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
    for row in audits:
        if row["verdict"] == "SUPPORTED" and row["reason_code"] == "ENTAILED":
            supported_audits[(row["page_id"], row["claim_id"])].add((
                row["claim_text"], tuple(sorted(json.loads(row["source_ids"]))),
            ))
    claims_by_page = Counter()
    for row in claims:
        claims_by_page[row["page_id"]] += 1
        sources = json.loads(row["sources_json"])
        if not sources:
            issue("claim", row["claim_id"], "NO_SOURCE")
        for source in sources:
            check_source(source, "claim", row["claim_id"])
        identity = (row["claim_text"], tuple(sorted(source["source_id"] for source in sources)))
        if identity not in supported_audits[(row["page_id"], row["claim_id"])]:
            issue("claim", row["claim_id"], "NO_EXACT_SUPPORTED_AUDIT")

    seen_page_keys = set()
    for row in pages:
        if int(row["claim_count"]) != claims_by_page[row["page_id"]]:
            issue("page", row["page_id"], "CLAIM_COUNT_MISMATCH")
        key = (row["page_type"], row["slug"].casefold())
        if key in seen_page_keys:
            issue("page", row["page_id"], "DUPLICATE_TYPE_SLUG")
        seen_page_keys.add(key)

    report = {
        "evaluation_label": "AI_ASSISTED_DETERMINISTIC_AUDIT",
        "status": "PASS" if not issues else "PARTIAL",
        "gate_c": "NOT_RUN", "human_review": "NOT_RUN",
        "cohort_sha256": hashlib.sha256(cohort_bytes).hexdigest(),
        "counts": {
            "documents": len(documents), "evidence_chunks": len(evidence),
            "candidates": len(candidates), "identities": len(identities),
            "pages": len(pages), "claims": len(claims),
            "audit_events": len(audits), "source_bindings_checked": checks["source_bindings"],
        },
        "issue_counts": dict(Counter(item["code"] for item in issues)),
        "issues": issues,
        "limits": ["No semantic entailment judgment", "No human signature",
                   "Exact duplicate slug check does not establish semantic page uniqueness"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "gate_c", "counts", "issue_counts",
    )}, ensure_ascii=False))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
