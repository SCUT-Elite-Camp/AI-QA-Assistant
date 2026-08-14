"""Ingest selected FinanceBench PDFs into an isolated retrieval index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The project embedding model is already cached locally. Avoid network version
# checks and accidental model downloads while preparing an evaluation corpus.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
for path in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence", ROOT / "toolset"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from parsers.registry import parse_file
from pipeline.chunker import chunk_from_blocks, chunk_text
from pipeline.embedder import embed_texts
from retrieval.bm25_index import BM25Index
from storage.milvus_store import MilvusStore

DEFAULT_PDFS = ROOT / "eval" / "datasets" / "external" / "financebench_subset" / "pdfs"
DEFAULT_NAMESPACE = "financebench_eval"


def namespace_paths(namespace: str) -> tuple[Path, Path, str]:
    if not namespace.replace("_", "").isalnum():
        raise ValueError("namespace must contain only letters, digits, and underscores")
    base = ROOT / "data-persistence" / "data" / "namespaces" / namespace
    return base / "documents", base / "bm25_index.pkl", f"{namespace}_chunks"


def ingest(pdf_dir: Path, namespace: str, chunk_size: int, overlap: int) -> dict:
    documents_dir, bm25_path, collection_name = namespace_paths(namespace)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"no PDFs found in {pdf_dir}")
    documents_dir.mkdir(parents=True, exist_ok=True)
    milvus = MilvusStore()
    processed = 0
    total_chunks = 0

    for index, pdf in enumerate(pdfs, start=1):
        print(f"[{index}/{len(pdfs)}] {pdf.name}")
        parsed = parse_file(str(pdf))
        docs = parsed if isinstance(parsed, list) else [parsed]
        for doc in docs:
            chunks = (
                chunk_from_blocks(doc.content_blocks, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
                if doc.content_blocks
                else chunk_text(doc.content, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
            )
            if not chunks:
                continue
            doc.chunks = chunks
            (documents_dir / f"{doc.doc_id}.json").write_text(
                json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            embeddings = embed_texts([chunk.text for chunk in chunks])
            try:
                milvus.init_collection(collection_name=collection_name, dim=len(embeddings[0]))
                milvus.collection.delete(expr=f"doc_id == '{doc.doc_id}'")
            except Exception:
                pass
            milvus.insert_chunks(
                embeddings=embeddings,
                chunk_ids=[chunk.chunk_id for chunk in chunks],
                chunk_texts=[chunk.text for chunk in chunks],
                doc_ids=[doc.doc_id] * len(chunks),
                chunk_indices=[chunk.index for chunk in chunks],
                source_urls=[doc.source_url] * len(chunks),
                collection_name=collection_name,
            )
            processed += 1
            total_chunks += len(chunks)

    bm25 = BM25Index()
    bm25.build_from_documents(str(documents_dir))
    bm25.save(str(bm25_path))
    result = {
        "namespace": namespace,
        "collection": collection_name,
        "documents_dir": str(documents_dir),
        "bm25_path": str(bm25_path),
        "documents": processed,
        "chunks": total_chunks,
    }
    (documents_dir.parent / "ingestion_summary.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated FinanceBench ingestion")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDFS)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--overlap", type=int, default=120)
    args = parser.parse_args()
    print(json.dumps(ingest(args.pdf_dir, args.namespace, args.chunk_size, args.overlap), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
