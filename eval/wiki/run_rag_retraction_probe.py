"""Isolated real-Milvus check for Confluence document retraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence", ROOT / "toolset"):
    sys.path.insert(0, str(dependency))

from pipeline.embedder import embed_texts  # noqa: E402
from pipeline.rag_lifecycle import (  # noqa: E402
    finish_retraction, mark_retraction_pending, pending_confluence_retractions,
)
from retrieval.bm25_index import BM25Index  # noqa: E402
from storage.milvus_store import MilvusStore  # noqa: E402
from toolset.tool_layer.search_tool import SearchTool  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--milvus-port", type=int, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    documents = args.output_dir / "documents"
    export = args.output_dir / "confluence" / "space"
    documents.mkdir(parents=True)
    export.mkdir(parents=True)
    collection_name = "wiki_delete_eval_" + hashlib.sha256(
        str(args.output_dir.resolve()).encode(),
    ).hexdigest()[:12]
    texts = ["obsolete document unique evidence", "active document unique evidence"]
    for index, content in enumerate(texts, 1):
        (documents / f"doc-{index}.json").write_text(json.dumps({
            "doc_id": f"doc-{index}", "active_version": True,
            "metadata": {"space_id": "space-1", "page_id": f"page-{index}"},
            "chunks": [{"chunk_id": f"chunk-{index}", "index": 0, "text": content}],
        }), encoding="utf-8")
    (export / "manifest.json").write_text(json.dumps({
        "source_type": "confluence_cloud", "status": "ok", "full_sync": True,
        "space_id": "space-1", "pages": {"page-2": {}},
    }), encoding="utf-8")
    milvus = MilvusStore(host="127.0.0.1", port=str(args.milvus_port),
                         collection_name=collection_name)
    vectors = embed_texts(texts)
    milvus.insert_chunks(
        embeddings=vectors, chunk_ids=["chunk-1", "chunk-2"],
        chunk_texts=texts, doc_ids=["doc-1", "doc-2"], chunk_indices=[0, 0],
    )
    before = milvus.search_similar(query_vector=vectors[0], top_k=2,
                                   doc_ids_filter=["doc-1"])
    if not before:
        raise ValueError("isolate has no document vectors before retraction")
    pending = pending_confluence_retractions(documents, args.output_dir / "confluence")
    if [value.document_id for value in pending] != ["doc-1"]:
        raise ValueError("full-export omission did not select exactly one document")
    mark_retraction_pending(pending[0])
    direct = SearchTool(documents_dir=str(documents))
    direct._milvus_store = milvus
    hidden_before_cleanup = not any(
        item.get("doc_id") == "doc-1"
        for item in direct._normalize_results([{
            "doc_id": "doc-1", "chunk_id": "chunk-1", "chunk_index": 0,
            "chunk_text": texts[0], "score": 1.0,
        }], {}, 0.0)
    )
    milvus.delete_document_chunks("doc-1")
    index = BM25Index()
    index.build_from_documents(str(documents))
    index.save(str(args.output_dir / "bm25.pkl"))
    after = milvus.search_similar(query_vector=vectors[0], top_k=2,
                                  doc_ids_filter=["doc-1"])
    active = milvus.search_similar(query_vector=vectors[1], top_k=2,
                                   doc_ids_filter=["doc-2"])
    finish_retraction(pending[0])
    report = {
        "evaluation_label": "ISOLATED_RAG_RETRACTION_PROBE",
        "status": "PASS" if (
            hidden_before_cleanup and not after and bool(active)
            and index.document_count == 1
            and pending_confluence_retractions(documents, args.output_dir / "confluence") == []
        ) else "PARTIAL",
        "collection": collection_name, "before_vector_hits": len(before),
        "after_deleted_vector_hits": len(after), "remaining_vector_hits": len(active),
        "remaining_bm25_documents": index.document_count,
        "hidden_before_cleanup": hidden_before_cleanup,
        "production_modified": False,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
