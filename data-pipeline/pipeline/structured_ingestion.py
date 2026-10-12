"""Shared structured chunk preparation and vector provenance serialization."""

import json

from models.document import Chunk, Document
from pipeline.chunker import chunk_from_blocks, chunk_text


def prepare_ingestion_chunks(
    document: Document, *, chunk_size: int = 500, overlap: int = 100,
) -> list[Chunk]:
    if document.content_blocks:
        return chunk_from_blocks(
            document.content_blocks, document.doc_id, chunk_size=chunk_size,
            overlap=overlap, document_title=document.title,
        )
    return chunk_text(document.content, document.doc_id, chunk_size=chunk_size, overlap=overlap)


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
