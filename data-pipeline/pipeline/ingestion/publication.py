"""Publish prepared enterprise projections after enabled vector writes succeed."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from models.document import Document
from pipeline.ingestion.preparation import prepare_document
from pipeline.indexing.vectors import index_document_vectors
from pipeline.indexing.embedder import embed_texts
from data_persistence.documents import save_document
from data_persistence.wiki import resolve_wiki_db_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def index_document(
    doc: Document,
    *,
    chunk_size: int,
    overlap: int,
    evidence_milvus: Any,
    has_milvus: bool,
    section_milvus: Any | None = None,
) -> bool:
    prepare_document(doc, chunk_size=chunk_size, overlap=overlap)
    chunks = doc.chunks
    print(f"  → 分块完成，共 {len(chunks)} 个分块、{len(doc.sections)} 个章节")
    if not chunks:
        print("  [Warning] 分块内容为空，跳过该文档")
        return False

    # Retrieval vectors are deliberately built from the semantic view; the
    # stored chunk remains Markdown so citations and model context retain the
    # original layout.
    index_texts = [chunk.index_text or chunk.text for chunk in chunks]
    section_rows = [section for section in doc.sections if section.navigation_text]
    section_texts = [section.navigation_text for section in section_rows]
    print(f"  → 正在生成 {len(chunks)} 个 Evidence 向量")
    embeddings = embed_texts(index_texts) if has_milvus else []
    section_embeddings = embed_texts(section_texts) if has_milvus and section_texts else []

    if has_milvus:
        # Section and Evidence use different collections and ID namespaces.
        assert section_milvus is not None
        # Validate the target schema before replacing any live vectors.
        evidence_milvus.init_collection(dim=len(embeddings[0]))
        evidence_milvus.validate_chunk_schema()
        if section_rows:
            section_milvus.init_collection(dim=len(section_embeddings[0]))
            section_milvus.collection.delete(expr=f'doc_id == {json.dumps(doc.doc_id)}')
            section_milvus.collection.flush()
            section_milvus.insert_chunks(
                embeddings=section_embeddings,
                chunk_ids=[section.id for section in section_rows],
                chunk_texts=[section.navigation_text for section in section_rows],
                doc_ids=[doc.doc_id] * len(section_rows),
                chunk_indices=list(range(len(section_rows))),
                source_urls=[doc.source_url] * len(section_rows),
                titles=[section.title for section in section_rows],
                spaces=[doc.space] * len(section_rows),
                doc_types=["section"] * len(section_rows),
                collection_name=section_milvus.collection_name,
            )
        index_document_vectors(doc, evidence_milvus, embed=embed_texts, embeddings=embeddings)

    # The active JSON projection is switched only after all enabled indexes succeed.
    save_document(doc.doc_id, doc.model_dump(mode="json"))
    print(f"  → Saved document: {doc.doc_id}")
    if os.getenv("WIKI_INGEST_ENABLED", "false").strip().casefold() in {
        "1", "true", "yes",
    }:
        space_id = str(doc.metadata.get("space_id") or "").strip()
        if space_id:
            from pipeline.wiki.domain import WikiScope
            from pipeline.wiki.queue import WikiLifecycleCoordinator
            from pipeline.wiki.source import document_to_wiki_source
            from data_persistence.wiki import WikiStore

            source = document_to_wiki_source(
                doc,
                WikiScope(
                    source_scope="enterprise",
                    knowledge_base_id=os.getenv(
                        "ENTERPRISE_KNOWLEDGE_BASE_ID", "default"
                    ),
                ),
            )
            WikiLifecycleCoordinator(
                WikiStore(resolve_wiki_db_path(PROJECT_ROOT))
            ).document_ingested(source)
    return True
