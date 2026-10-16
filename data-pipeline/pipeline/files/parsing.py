"""Public, index-free parsing API shared by uploads and batch ingestion."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from models.document import Document


def normalized_bbox(document: Document, box, page_number: int | None):
    values = list(box.model_dump().values())
    size = document.metadata.get("page_sizes", {}).get(str(page_number))
    if size and size[0] > 0 and size[1] > 0:
        values = [value / size[index % 2] for index, value in enumerate(values)]
    return values


def parse_document(file_path: str | Path) -> list[Document]:
    """Parse a local file without indexing, persistence or remote downloads."""
    from parsers.registry import parse_file

    return parse_file(str(file_path))


def document_evidence(documents: list[Document], source_id: str) -> list[dict[str, Any]]:
    """Preserve source geometry in the existing citation wire format."""
    items = []
    for document in documents:
        blocks = document.content_blocks
        for index, block in enumerate(blocks):
            content = block.to_index_markdown()
            if not content.strip():
                continue
            locator = dict(block.locator)
            if not locator:
                locator["block"] = index
            if block.page_number is not None:
                locator["page"] = block.page_number
            if block.bbox is not None:
                locator["bbox"] = normalized_bbox(document, block.bbox, block.page_number)
            items.append({
                "evidence_id": f"{source_id}_block_{len(items)}",
                "attachment_id": source_id,
                "source_type": "table" if block.block_type == "table" else (
                    "ocr_text" if block.source == "ocr" else "document_text"
                ),
                "content": content, "locator": locator,
                "confidence": block.confidence,
                "parser": block.extraction_method or "pipeline",
            })
        if not blocks and document.content.strip():
            items.append({
                "evidence_id": f"{source_id}_block_{len(items)}", "attachment_id": source_id,
                "source_type": "document_text", "content": document.content,
                "locator": {}, "confidence": 1.0, "parser": "pipeline",
            })
    return items


def parse_context(file_path: str | Path, source_id: str) -> dict[str, Any]:
    documents = parse_document(file_path)
    items = document_evidence(documents, source_id)
    return {
        "context": "\n\n".join(item["content"] for item in items),
        "items": items,
        "documents": [document.model_dump(mode="json") for document in documents],
    }
