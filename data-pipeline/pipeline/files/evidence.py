"""Adapt durable file snapshots and evidence to canonical documents."""
from typing import Any
from models.document import Chunk, Document
from pipeline.ingestion.preparation import prepare_document
from pipeline.files.parsing import normalized_bbox


def prepare_persisted_document(parsed: dict[str, Any], attachment: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    if parsed.get("source_sha256") != attachment["sha256"]:
        raise ValueError("parsed_source_hash_mismatch")
    version = str(attachment.get("version_id") or attachment["id"])
    evidence, sections = [], []
    for ordinal, raw in enumerate(parsed["documents"]):
        document = Document.model_validate(raw)
        document.doc_id = version if ordinal == 0 else f"{version}_part_{ordinal}"
        document.version_id = document.doc_id
        document.title = attachment["filename"]
        prepare_document(document)
        for chunk in document.chunks:
            locator = {
                **dict(chunk.metadata.get("locator") or {}),
                "chunk_index": chunk.index, "section_path": chunk.section_path,
            }
            for key in ('previous_chunk_id', 'next_chunk_id', 'row_start', 'row_end'):
                if key in chunk.metadata:
                    locator[key] = chunk.metadata[key]
            if chunk.page_number is not None:
                locator["page"] = chunk.page_number
            if chunk.block_start is not None:
                locator["block"] = chunk.block_start
                if chunk.block_start < len(document.content_blocks):
                    locator = {**document.content_blocks[chunk.block_start].locator, **locator}
            if chunk.bbox is not None:
                locator["bbox"] = normalized_bbox(document, chunk.bbox, chunk.page_number)
            evidence.append({
                "evidence_id": chunk.chunk_id, "attachment_id": attachment["id"],
                "content": chunk.markdown_text or chunk.text,
                "index_text": chunk.index_text,
                "chunk": chunk.model_dump(mode="json"),
                "filename": attachment["filename"],
                "knowledge_base_id": attachment.get("knowledge_base_id", ""),
                "source_type": "table" if chunk.chunk_type in {"table", "table_row"} else "document_text",
                "locator": locator, "confidence": chunk.metadata.get("confidence", 1.0), "parser": "pipeline",
            })
        sections.extend({**section.model_dump(mode="json"), "attachment_id": attachment["id"]}
                        for section in document.sections)
    return evidence, sections


def persisted_evidence_document(projection_id: str, evidence: list[dict]) -> Document:
    """Adapt a stored file's evidence to the canonical indexing input."""
    content = [item for item in evidence if str(item.get("content") or "").strip()]
    chunks = [Chunk.model_validate(item["chunk"]) if "chunk" in item else Chunk(
        chunk_id=item["evidence_id"], index=ordinal, text=item["content"],
        markdown_text=item["content"], index_text=item.get("index_text") or item["content"],
    ) for ordinal, item in enumerate(content)]
    first = content[0] if content else {}
    source_id = projection_id.partition("__")[0]
    return Document(
        doc_id=projection_id, title=first.get("filename", source_id),
        content="", space=first.get("knowledge_base_id") or "attachment", address="",
        last_updated="", chunks=chunks, doc_type="attachment",
        source_url=f"/api/attachments/{source_id}/content",
    )
