"""Isolated Phase 8 integration probe over the frozen real Confluence cohort.

The only activated Wiki revision is in a new SQLite backup. Agent model decisions
are scripted; Wiki storage/vector search and Direct BM25 Evidence are real local
implementations. This is not Gate D or a production publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "agent", ROOT / "toolset", ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(dependency))

from agent.config.settings import settings  # noqa: E402
from agent.llm.llm_client import LLMClient  # noqa: E402
from agent.runtime import AgentRunner, StopReason  # noqa: E402
from agent.schemas.intent_policy import IntentPolicy  # noqa: E402
from agent.schemas.query_plan import QueryIntent, QueryPlan  # noqa: E402
from agent.service.audit_service import AuditService  # noqa: E402
from agent.tools import ToolExecutor, ToolRegistryAdapter  # noqa: E402
from pipeline.confluence_snapshot import discover_confluence_snapshots  # noqa: E402
from pipeline.embedder import embed_texts  # noqa: E402
from pipeline.wiki.confluence_source import load_authoritative_confluence_document  # noqa: E402
from pipeline.wiki.search import BgeM3WikiVectorSearch, SQLiteFTSWikiSearch, WikiSearchBackend  # noqa: E402
from retrieval.bm25_index import BM25Index  # noqa: E402
from storage.wiki_store import WikiStore  # noqa: E402
from storage.milvus_store import MilvusStore  # noqa: E402
from toolset.tool_layer import SearchTool, ToolRegistry  # noqa: E402
from toolset.tool_layer.wiki_tool import (  # noqa: E402
    WikiReadPageTool, WikiReadSourcesTool, WikiSearchEvidenceTool, WikiSearchTool,
)


class ScriptedExplorer:
    def __init__(self, page_id: str) -> None:
        self.page_id = page_id
        self.calls = 0

    def chat(self, messages, tools=None):
        actions = (
            ("wiki_search", {}),
            ("wiki_read_page", {"page_ref": self.page_id}),
            ("wiki_read_sources", {"page_id": self.page_id}),
            ("wiki_search_evidence", {"page_id": self.page_id}),
        )
        if self.calls >= len(actions):
            return {"role": "assistant", "content": "已检索原始 Evidence [1]。"}
        name, arguments = actions[self.calls]
        self.calls += 1
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"phase8-{self.calls}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confluence-root", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--milvus-port", type=int)
    parser.add_argument("--reviewed-only", action="store_true",
                        help="In the isolated clone, exclude FAILED pages and remove links to them")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite integration run: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    started = time.perf_counter()

    cohort_bytes = args.cohort.read_bytes()
    cohort = json.loads(cohort_bytes.decode("utf-8-sig"))
    cohort_hash = hashlib.sha256(cohort_bytes).hexdigest()
    snapshots = {item.identity: item for item in discover_confluence_snapshots(
        args.confluence_root, require_storage=True,
    )}
    docs_dir = args.output_dir / "documents"
    docs_dir.mkdir()
    document_ids = set()
    evidence_ids = set()
    direct_chunks = []
    for item in cohort["pages"]:
        snapshot = snapshots[tuple(item["identity"])]
        if (snapshot.content_sha256 != item["content_sha256"]
                or snapshot.source_content_sha256 != item["source_content_sha256"]):
            raise ValueError("frozen Confluence cohort changed")
        document = load_authoritative_confluence_document(snapshot)
        document_ids.add(document.doc_id)
        evidence_ids.update(chunk.chunk_id for chunk in document.chunks)
        direct_chunks.extend((document, chunk) for chunk in document.chunks)
        payload = {
            "doc_id": document.doc_id, "version_id": document.version_id,
            "active_version": document.active_version,
            "title": document.title, "source_url": document.source_url,
            "space": str(cohort["space_id"]), "knowledge_base_id": str(cohort["space_id"]),
            "doc_type": "md",
            "chunks": [{"index": chunk.index, "chunk_id": chunk.chunk_id, "text": chunk.text}
                       for chunk in document.chunks],
        }
        (docs_dir / f"{document.doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )

    index = BM25Index()
    index.build_from_documents(str(docs_dir))
    if index.document_count != len(document_ids):
        raise ValueError("Direct Evidence index omitted a frozen document")
    direct = SearchTool(documents_dir=str(docs_dir))
    direct._bm25_index = index
    direct_mode = "bm25"
    collection_name = "wiki_eval_" + hashlib.sha256(
        str(args.output_dir.resolve()).encode("utf-8"),
    ).hexdigest()[:16]
    if args.milvus_port is not None:
        if not 1 <= args.milvus_port <= 65535:
            raise ValueError("Milvus port is invalid")
        milvus = MilvusStore(host="127.0.0.1", port=str(args.milvus_port),
                             collection_name=collection_name)
        vectors = embed_texts([chunk.text for _document, chunk in direct_chunks])
        milvus.insert_chunks(
            embeddings=vectors,
            chunk_ids=[chunk.chunk_id for _document, chunk in direct_chunks],
            chunk_texts=[chunk.text for _document, chunk in direct_chunks],
            doc_ids=[document.doc_id for document, _chunk in direct_chunks],
            chunk_indices=[chunk.index for _document, chunk in direct_chunks],
            source_urls=[document.source_url for document, _chunk in direct_chunks],
            titles=[document.title for document, _chunk in direct_chunks],
            spaces=[str(cohort["space_id"])] * len(direct_chunks),
            doc_types=["md"] * len(direct_chunks),
        )
        direct._milvus_store = milvus
        direct_mode = "vector"

    source_db = sqlite3.connect(args.source_db)
    source_status = source_db.execute(
        "SELECT status FROM wiki_build_runs WHERE revision=? AND source_scope='enterprise' "
        "AND owner_id='' AND knowledge_base_id=?",
        (args.revision, str(cohort["space_id"])),
    ).fetchone()
    if source_status is None or source_status[0] != "DRAFT":
        raise ValueError("isolated integration requires an unchanged DRAFT source revision")
    clone_db = sqlite3.connect(args.output_dir / "wiki.sqlite3")
    source_db.backup(clone_db)
    source_db.close()
    clone_db.close()
    excluded_pages = 0
    if args.reviewed_only:
        excluded_pages = _retain_reviewed_pages(
            args.output_dir / "wiki.sqlite3", args.revision, str(cohort["space_id"]),
        )
    store = WikiStore(args.output_dir / "wiki.sqlite3")
    scope = dict(source_scope="enterprise", owner_id="", knowledge_base_id=str(cohort["space_id"]))
    store.publish_revision(**scope, revision=args.revision)

    vector = BgeM3WikiVectorSearch(store)
    indexed_wiki_pages = vector.index_active_revision(**scope)
    if indexed_wiki_pages < 1:
        raise ValueError("isolated Wiki vector index has no pages")
    backend = WikiSearchBackend(SQLiteFTSWikiSearch(store), vector)
    with store.connection() as db:
        candidates = db.execute(
            "SELECT r.page_id,r.title,COUNT(DISTINCT s.document_id) AS documents "
            "FROM wiki_page_revisions r JOIN wiki_page_sources s ON "
            "r.source_scope=s.source_scope AND r.owner_id=s.owner_id "
            "AND r.knowledge_base_id=s.knowledge_base_id AND r.revision=s.revision "
            "AND r.page_id=s.page_id WHERE r.revision=? AND r.page_type!='INDEX' "
            "GROUP BY r.page_id,r.title ORDER BY documents DESC,r.page_id",
            (args.revision,),
        ).fetchall()
    if not candidates:
        raise ValueError("frozen Wiki revision has no sourced pages")
    query = "跨文档比较 " + str(candidates[0]["title"])
    direct_milvus_hits = 0
    if args.milvus_port is not None:
        direct_milvus_hits = len(milvus.search_similar(
            query_vector=embed_texts([query])[0], top_k=5,
        ))
        if not direct_milvus_hits:
            raise ValueError("isolated Milvus Direct Evidence returned no hits")
    wiki_candidates = backend.search(query, **scope, top_k=8)
    wiki_vector_hits = vector.search(query, **scope, top_k=8)
    if not wiki_vector_hits:
        raise ValueError("isolated Wiki BGE-M3 vector search returned no pages")
    if not wiki_candidates:
        raise ValueError("real FTS/vector Wiki search returned no pages")
    page_id = next((page["page_id"] for page in wiki_candidates
                    if store.read_sources(page["page_id"], **scope)), "")
    if not page_id:
        raise ValueError("Wiki search returned no page with source Evidence")

    wiki_search = WikiSearchTool(store, enterprise_knowledge_base_id=scope["knowledge_base_id"],
                                 search_backend=backend)
    wiki_page = WikiReadPageTool(store, enterprise_knowledge_base_id=scope["knowledge_base_id"])
    wiki_sources = WikiReadSourcesTool(store, enterprise_knowledge_base_id=scope["knowledge_base_id"])
    wiki_evidence = WikiSearchEvidenceTool(store, direct,
                                           enterprise_knowledge_base_id=scope["knowledge_base_id"])
    tools = [direct, wiki_search, wiki_page, wiki_sources, wiki_evidence]
    registry = ToolRegistry(tools=tools)
    plan = QueryPlan(original_query=query, standalone_query=query, intent=QueryIntent.COMPARISON)
    policy = IntentPolicy(candidate_tools=tuple(tool.name for tool in tools),
                          max_iterations=7, max_tool_calls=8, max_retrieval_attempts=5)
    previous = settings.AGENTIC_EXPLORATION_ENABLED
    settings.AGENTIC_EXPLORATION_ENABLED = True
    if args.live_model:
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise ValueError("DEEPSEEK_API_KEY is required for live-model integration")
        settings.LLM_API_KEY = key
        settings.LLM_API_BASE = "https://api.deepseek.com"
        settings.LLM_MODEL = "deepseek-v4-flash"
        model = LLMClient()
    else:
        model = ScriptedExplorer(page_id)
    try:
        result = AgentRunner(model, registry, AuditService()).run(
            plan, policy=policy, tool_executor=ToolExecutor(ToolRegistryAdapter(registry),
                                                             timeout_ms=120000),
            trace_id="isolated-phase8", mode=direct_mode, top_k=5,
            exploration_mode="auto", navigation_scopes=("enterprise",),
        )
    finally:
        settings.AGENTIC_EXPLORATION_ENABLED = previous

    expected_tools = ["search_documents", "wiki_search", "wiki_read_page",
                      "wiki_read_sources", "wiki_search_evidence"]
    tool_order = [call.tool_name for call in result.tool_calls]
    successful_order = [call.tool_name for call in result.tool_calls if call.success]
    sources = store.read_sources(page_id, **scope)
    allowed_versions = {(row["document_id"], row["document_version_id"]) for row in sources}
    scoped_results = wiki_evidence.execute(query=query, page_id=page_id, mode=direct_mode)
    items = scoped_results.get("items") or []
    source_version_valid = bool(items) and all(
        (item["document_id"], item["version_id"]) in allowed_versions
        and item["chunk_id"] in evidence_ids for item in items
    )
    agent_scoped = [item for item in result.evidence if (
        (str(item.get("document_id") or item.get("doc_id") or ""),
         str(item.get("version_id") or "")) in allowed_versions
        and str(item.get("chunk_id") or "") in evidence_ids
    )]
    wrong_scope_empty = not wiki_search.execute(query=query, source_scope="personal").get("pages")
    wrong_kb_empty = not WikiSearchTool(
        store, enterprise_knowledge_base_id="unauthorized-kb", search_backend=backend,
    ).execute(query=query).get("pages")
    with store.connection() as db:
        vector_page_count = db.execute(
            "SELECT COUNT(*) FROM wiki_page_vectors WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? AND model_id='BAAI/bge-m3'",
            (scope["source_scope"], scope["owner_id"], scope["knowledge_base_id"], args.revision),
        ).fetchone()[0]
    report = {
        "evaluation_label": "ISOLATED_INTEGRATION_PROBE",
        "status": "PASS" if (
            result.stop_reason == StopReason.FINAL_ANSWER and successful_order == expected_tools
            and source_version_valid and agent_scoped and wrong_scope_empty and wrong_kb_empty
            and vector_page_count == indexed_wiki_pages and bool(wiki_vector_hits)
            and (args.milvus_port is None or direct_milvus_hits > 0)
        ) else "PARTIAL",
        "gate_d": "NOT_RUN", "production_published": False,
        "source_revision_status": "DRAFT", "isolated_clone_published": True,
        "isolated_reviewed_subset": args.reviewed_only,
        "failed_pages_excluded": excluded_pages,
        "source_cohort_sha256": cohort_hash, "source_revision": args.revision,
        "agent_model": "deepseek-v4-flash" if args.live_model else "scripted",
        "source_documents": len(document_ids), "direct_evidence_chunks": index.chunk_count,
        "direct_backend": "MILVUS_BGE_M3" if args.milvus_port is not None else "BM25",
        "isolated_milvus_collection": collection_name if args.milvus_port is not None else "",
        "wiki_vector_pages": vector_page_count,
        "wiki_vector_hits": len(wiki_vector_hits),
        "direct_milvus_hits": direct_milvus_hits,
        "wiki_candidate_count": len(wiki_candidates),
        "tool_order": tool_order, "successful_tool_order": successful_order,
        "stop_reason": str(result.stop_reason),
        "tool_outcomes": [{"name": call.tool_name, "success": call.success,
                           "error_code": call.error_code} for call in result.tool_calls],
        "exploration_rounds": result.exploration_rounds,
        "agent_evidence_count": len(result.evidence),
        "agent_scoped_evidence_count": len(agent_scoped),
        "scoped_evidence_count": len(items),
        "source_version_valid": source_version_valid,
        "wrong_scope_empty": wrong_scope_empty, "wrong_knowledge_base_empty": wrong_kb_empty,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "limits": (["isolated Wiki database copy", "no live Confluence or serving latency or Gate D labels"]
                   + (["failed pages excluded only in isolated clone"] if args.reviewed_only else [])
                   + ([] if args.milvus_port is not None else ["BM25-only Direct Evidence"])
                   + ([] if args.live_model else ["scripted Agent model"])),
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


def _retain_reviewed_pages(database: Path, revision: str, knowledge_base_id: str) -> int:
    """Prepare a disposable navigation subset without changing the source revision."""
    context = ("enterprise", "", knowledge_base_id, revision)
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        pages = db.execute(
            "SELECT page_id,slug,status,payload FROM wiki_page_revisions WHERE "
            "source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?", context,
        ).fetchall()
        if not pages or any(row["status"] not in {"REVIEWING", "FAILED"} for row in pages):
            raise ValueError("reviewed-only probe requires a DRAFT revision with reviewed or failed pages")
        kept = {row["page_id"]: row for row in pages if row["status"] == "REVIEWING"}
        if not kept:
            raise ValueError("reviewed-only probe has no review-passed pages")
        slugs = {row["slug"] for row in kept.values()}
        missing = [row["page_id"] for row in pages if row["status"] == "FAILED"]
        db.execute("BEGIN IMMEDIATE")
        for page_id in missing:
            for table in (
                "wiki_page_links", "wiki_page_sources", "wiki_page_claims",
                "wiki_claim_audits", "wiki_claim_repairs", "wiki_page_revisions",
            ):
                db.execute(
                    f"DELETE FROM {table} WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=? AND page_id=?",
                    (*context, page_id),
                )
        link_pattern = re.compile(r"\[([^\]]+)\]\(/wiki/([^\)]+)\)")
        def strip_missing_links(value: str) -> str:
            return link_pattern.sub(
                lambda match: match.group(0) if match.group(2) in slugs else match.group(1),
                value,
            )
        for page_id, row in kept.items():
            payload = json.loads(row["payload"])
            payload["links"] = sorted(set(payload.get("links") or []) & set(kept) - {page_id})
            payload["summary"] = strip_missing_links(payload.get("summary") or "")
            for section in payload.get("sections") or []:
                for claim in section.get("claims") or []:
                    claim["rendered_text"] = strip_missing_links(claim.get("rendered_text") or "")
            db.execute(
                "UPDATE wiki_page_revisions SET summary=?,payload=? WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=?",
                (payload["summary"], json.dumps(payload, ensure_ascii=False), *context, page_id),
            )
            db.execute(
                "DELETE FROM wiki_page_links WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND page_id=?", (*context, page_id),
            )
            for target in payload["links"]:
                db.execute("INSERT INTO wiki_page_links VALUES(?,?,?,?,?,?)", (*context, page_id, target))
        db.commit()
        return len(missing)


if __name__ == "__main__":
    main()
