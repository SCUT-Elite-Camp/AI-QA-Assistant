"""Read-only retrieval component PROBE on the frozen 12-page Wiki cohort.

Queries and relevance are weak labels derived from Wiki pages. This is neither
an Agent run nor a substitute for the human-frozen Gate D dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(dependency))

from pipeline.confluence_snapshot import discover_confluence_snapshots  # noqa: E402
from pipeline.wiki.confluence_source import load_authoritative_confluence_document  # noqa: E402
from pipeline.wiki.domain import WikiScope  # noqa: E402
from pipeline.wiki.search import BgeM3Encoder  # noqa: E402
from pipeline.wiki.source import document_to_wiki_source  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _top(vector: np.ndarray, matrix: np.ndarray, indices: list[int], limit: int) -> list[int]:
    scores = matrix[indices] @ vector
    return [indices[position] for position in np.argsort(-scores, kind="stable")[:limit]]


def _queries(db: sqlite3.Connection, revision: str, per_type: int) -> list[dict]:
    pages = db.execute(
        "SELECT page_id,page_type,title FROM wiki_page_revisions WHERE revision=? AND page_type!='INDEX'",
        (revision,),
    ).fetchall()
    sources: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in db.execute(
        "SELECT page_id,document_version_id,evidence_id FROM wiki_page_sources WHERE revision=?",
        (revision,),
    ):
        sources[row["page_id"]].add((row["document_version_id"], row["evidence_id"]))
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for page in pages:
        refs = sources[page["page_id"]]
        if not refs:
            continue
        if page["page_type"] in {"CONCEPT", "ENTITY", "SUMMARY"}:
            groups[page["page_type"].lower()].append(page)
        if len({document for document, _ in refs}) >= 2:
            groups["cross_page"].append(page)
    selected = []
    for kind in ("cross_page", "concept", "entity", "summary"):
        ranked = sorted(groups[kind], key=lambda page: _sha256(f"wiki-retrieval-probe-v1:{kind}:{page['page_id']}".encode()))
        for page in ranked[:per_type]:
            selected.append({
                "query_id": f"probe-{kind}-{page['page_id']}", "query_type": kind,
                "query": f"{page['title']}有哪些相关讨论？",
                "seed_page_id": page["page_id"],
                "weak_relevant_sources": sorted(sources[page["page_id"]]),
            })
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("confluence_root", type=Path)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--wiki-db", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-type", type=int, default=5)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite retrieval PROBE: {args.output_dir}")
    cohort_bytes = args.cohort.read_bytes()
    cohort = json.loads(cohort_bytes.decode("utf-8-sig"))
    snapshots = {item.identity: item for item in discover_confluence_snapshots(args.confluence_root, require_storage=True)}
    scope = WikiScope(source_scope="enterprise", knowledge_base_id=str(cohort["space_id"]))
    documents = []
    for item in cohort["pages"]:
        snapshot = snapshots[tuple(item["identity"])]
        if snapshot.content_sha256 != item["content_sha256"] or snapshot.source_content_sha256 != item["source_content_sha256"]:
            raise ValueError("frozen source cohort changed")
        documents.append(document_to_wiki_source(load_authoritative_confluence_document(snapshot), scope))
    evidence = [(document.document_version_id, chunk.evidence_id, document.document_id, chunk.text)
                for document in documents for chunk in document.chunks]
    with sqlite3.connect(f"file:{args.wiki_db.resolve().as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT status FROM wiki_build_runs WHERE revision=? AND source_scope=? AND knowledge_base_id=?",
                         (args.revision, scope.source_scope, scope.knowledge_base_id)).fetchone()
        if run is None or run["status"] != "DRAFT":
            raise ValueError("component PROBE expects the unchanged DRAFT revision")
        queries = _queries(db, args.revision, args.per_type)
        raw_vectors = db.execute("SELECT page_id,embedding FROM wiki_page_vectors WHERE revision=? AND model_id='BAAI/bge-m3'",
                                 (args.revision,)).fetchall()
        page_vectors = {row["page_id"]: np.frombuffer(row["embedding"], dtype=np.float32) for row in raw_vectors}
        expected_page_ids = {row["page_id"] for row in db.execute(
            "SELECT page_id FROM wiki_page_revisions WHERE revision=?", (args.revision,),
        )}
        page_documents: dict[str, set[str]] = defaultdict(set)
        for row in db.execute("SELECT page_id,document_id FROM wiki_page_sources WHERE revision=?", (args.revision,)):
            page_documents[row["page_id"]].add(row["document_id"])
    if not queries or set(page_vectors) != expected_page_ids:
        raise ValueError("frozen component PROBE is missing queries or the indexed draft pages")
    encoder = BgeM3Encoder()
    start = time.perf_counter()
    evidence_vectors = np.asarray(encoder.embed([item[3] for item in evidence]), dtype=np.float32)
    query_vectors = np.asarray(encoder.embed([item["query"] for item in queries]), dtype=np.float32)
    page_ids = sorted(page_vectors)
    page_matrix = np.stack([page_vectors[page_id] for page_id in page_ids])
    all_indices = list(range(len(evidence)))
    records = []
    for query, vector in zip(queries, query_vectors):
        direct = _top(vector, evidence_vectors, all_indices, 20)
        wiki = _top(vector, page_matrix, list(range(len(page_ids))), 3)
        wiki_ids = [page_ids[index] for index in wiki]
        prioritized_docs = set().union(*(page_documents[page_id] for page_id in wiki_ids))
        scoped = [index for index, row in enumerate(evidence) if row[2] in prioritized_docs]
        guided = _top(vector, evidence_vectors, scoped, 20) if scoped else []
        # This is an offline candidate pool: keep a direct reserve and append
        # source-scoped Evidence. It is not the Agent's P1 decision or ranking.
        combined = list(dict.fromkeys(direct[:5] + guided + direct))[:20]
        relevant = {tuple(pair) for pair in query["weak_relevant_sources"]}
        keys = lambda values: [(evidence[index][0], evidence[index][1]) for index in values]
        direct_keys, combined_keys = keys(direct), keys(combined)
        records.append({
            **query, "p0_evidence": direct_keys, "guided_evidence": combined_keys,
            "wiki_page_candidates": wiki_ids,
            "p0_weak_recall_at_20": len(set(direct_keys) & relevant) / len(relevant),
            "guided_weak_recall_at_20": len(set(combined_keys) & relevant) / len(relevant),
        })
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["query_type"]].append(record)
    metrics = {kind: {
        "queries": len(values),
        "p0_weak_recall_at_20": round(sum(row["p0_weak_recall_at_20"] for row in values) / len(values), 4),
        "guided_weak_recall_at_20": round(sum(row["guided_weak_recall_at_20"] for row in values) / len(values), 4),
    } for kind, values in groups.items()}
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "query-records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "evaluation_label": "PROBE", "status": "PARTIAL", "gate_d": "NOT_RUN",
        "cohort_sha256": _sha256(cohort_bytes), "revision": args.revision,
        "revision_status": "DRAFT", "published": False,
        "query_count": len(queries), "query_origin": "Wiki-page-derived, weak labels; optimistic bias",
        "direct_retriever": "local BGE-M3 brute-force over exact 12-page Evidence",
        "guided_retriever": "draft Wiki BGE-M3 page vectors plus source-scoped Evidence rerank",
        "agent_exploration_run": False, "human_labels": False,
        "citation_faithfulness_latency_gate_run": False,
        "evidence_chunks": len(evidence), "wiki_vectors": len(page_vectors),
        "metrics": metrics, "elapsed_seconds": round(time.perf_counter() - start, 2),
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
