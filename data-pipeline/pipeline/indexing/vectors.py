"""Shared vector serialization, writing and process dispatch."""
import json
import os
import subprocess
import sys
from pathlib import Path
from models.document import Chunk, Document


def provenance_columns(chunks: list[Chunk]) -> dict[str, list]:
    def bbox_list(box):
        return [box.x0, box.y0, box.x1, box.y1]

    return {
        "chunk_types": [chunk.chunk_type for chunk in chunks],
        "block_ids": [chunk.block_id for chunk in chunks],
        "table_ids": [chunk.table_id for chunk in chunks],
        "page_numbers": [chunk.page_number or 0 for chunk in chunks],
        "bbox_jsons": [json.dumps(bbox_list(chunk.bbox)) if chunk.bbox else "" for chunk in chunks],
        "metadata_jsons": [json.dumps({
            **chunk.metadata, "source": chunk.source,
            "source_pages": chunk.source_pages,
            "page_regions": [
                {**region.model_dump(mode="json"), "bbox": bbox_list(region.bbox)}
                for region in chunk.page_regions
            ],
        }, ensure_ascii=False) for chunk in chunks],
    }


def replace_document_vectors(document: Document, store, embed, *, embeddings=None) -> None:
    """Write semantic embeddings and canonical display/provenance to the chosen store."""
    chunks = document.chunks
    if not chunks:
        return
    if embeddings is None:
        embeddings = embed([chunk.index_text or chunk.text for chunk in chunks])
    if len(embeddings) != len(chunks) or not embeddings or not embeddings[0]:
        raise ValueError("invalid_document_embeddings")
    store.init_collection(dim=len(embeddings[0]))
    store.validate_chunk_schema()
    store.collection.delete(expr=f'doc_id == {json.dumps(document.doc_id)}')
    store.collection.flush()
    store.insert_chunks(
        embeddings=embeddings,
        chunk_ids=[chunk.chunk_id for chunk in chunks],
        chunk_texts=[chunk.markdown_text or chunk.text for chunk in chunks],
        doc_ids=[document.doc_id] * len(chunks),
        chunk_indices=[chunk.index for chunk in chunks],
        source_urls=[document.source_url] * len(chunks),
        titles=[document.title] * len(chunks),
        spaces=[document.space] * len(chunks),
        doc_types=[document.doc_type] * len(chunks),
        **provenance_columns(chunks),
    )


def index_document_vectors(document: Document, store, *, embed=None, embeddings=None) -> None:
    """Run the common writer in a short-lived Windows process when loading a model."""
    if not document.chunks:
        return
    if os.name == "nt" and embed is None and embeddings is None:
        completed = subprocess.run(
            [sys.executable, "-m", "pipeline.indexing.worker"],
            input=json.dumps({
                "document": document.model_dump(mode="json"),
                "collection": store.collection_name, "host": store.host, "port": store.port,
            }, ensure_ascii=False),
            text=True, cwd=str(Path(__file__).resolve().parents[2]),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=float(os.getenv("VECTOR_PROCESS_TIMEOUT_SECONDS", os.getenv("ATTACHMENT_VECTOR_PROCESS_TIMEOUT_SECONDS", "120"))),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("vector_index_unavailable")
        return
    if embed is None:
        from pipeline.indexing.embedder import embed_texts
        embed = embed_texts
    store.connect()
    replace_document_vectors(document, store, embed, embeddings=embeddings)
