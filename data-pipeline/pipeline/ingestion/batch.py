"""Common backend setup, processing loop and index finalization for CLI ingestion."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models.document import Document
from parsers.registry import parse_file
from data_persistence.vector import MilvusStore
from data_persistence.documents import resolve_documents_dir, save_document
from retrieval.bm25_index import BM25Index
from pipeline.ingestion.publication import index_document
from pipeline.confluence.lifecycle import mark_retraction_pending, finish_retraction


@dataclass
class IndexTargets:
    evidence: object
    sections: object
    available: bool


def open_targets(host: str, port: str, *, required: bool = False) -> IndexTargets:
    evidence = MilvusStore(host=host, port=port)
    section_name = os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3").strip()
    if not section_name or section_name.casefold() == evidence.collection_name.strip().casefold():
        raise RuntimeError("SECTION_MILVUS_COLLECTION must differ from Evidence collection")
    sections = MilvusStore(host=host, port=port, collection_name=section_name)
    try:
        evidence.connect()
        sections.connect()
    except Exception as exc:
        if required:
            raise
        print(f"[Warning] Vector backend unavailable ({exc}); publishing lexical-only projections.")
        return IndexTargets(evidence, sections, False)
    return IndexTargets(evidence, sections, True)


def refresh_keyword_index(documents: list[Document], documents_dir: Path, *, vectors: bool) -> None:
    index = BM25Index()
    index.build_from_documents(str(documents_dir))
    index_path = os.getenv("BM25_INDEX_PATH") or str(documents_dir.parent / "bm25_index.pkl")
    index.save(index_path)
    indexed_at = datetime.now(timezone.utc).isoformat()
    for document in documents:
        document.metadata.update({
            "indexed_at": indexed_at, "sync_status": "ready" if vectors else "partial",
            "index_backends": ["bm25", "vector"] if vectors else ["bm25"],
            "index_generation": indexed_at,
        })
        save_document(document.doc_id, document.model_dump(mode="json"))


def run_batch(
    file_paths: list[str], *, chunk_size: int = 2000, overlap: int = 100,
    milvus_host: str = "localhost", milvus_port: str = "19530",
    strict: bool = False, require_vectors: bool = False,
    documents_dir: Path | None = None, retractions=(),
) -> list[Document]:
    """Apply the same processing and publication sequence to every selected file list."""
    if not file_paths and not retractions:
        return []
    documents_dir = Path(documents_dir) if documents_dir is not None else resolve_documents_dir()
    if documents_dir.resolve() != resolve_documents_dir().resolve():
        raise ValueError("documents_dir must match the configured persistence directory")
    targets = open_targets(milvus_host, milvus_port, required=strict or require_vectors)
    for retraction in retractions:
        mark_retraction_pending(retraction)
    cleaned = []
    for retraction in retractions:
        if not targets.available:
            continue
        try:
            targets.evidence.delete_document_chunks(retraction.document_id)
            targets.sections.delete_document_chunks(retraction.document_id)
            cleaned.append(retraction)
        except Exception as exc:
            if strict:
                raise
            print(f"[Warning] Retraction pending for {retraction.document_id}: {exc}")
    documents = []
    for file_path in file_paths:
        try:
            parsed = parse_file(str(Path(file_path).resolve()))
            if strict and not parsed:
                raise RuntimeError("Parser returned no documents during strict reindex")
            for document in parsed:
                indexed = index_document(
                    document, chunk_size=chunk_size, overlap=overlap,
                    evidence_milvus=targets.evidence, section_milvus=targets.sections,
                    has_milvus=targets.available,
                )
                if strict and not indexed:
                    raise RuntimeError("Document produced no chunks during strict reindex")
                if indexed:
                    documents.append(document)
        except Exception as exc:
            if strict:
                raise
            print(f"[Error] Failed to ingest {file_path}: {exc}")
    if documents or retractions:
        refresh_keyword_index(documents, documents_dir, vectors=targets.available)
        for retraction in cleaned:
            finish_retraction(retraction)
    return documents
