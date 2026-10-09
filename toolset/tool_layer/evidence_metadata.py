"""Version-bound provenance for authoritative document projections."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


class DocumentVersionConflict(ValueError):
    code = "document_version_changed"
    status_code = 409


def source_metadata(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    content = document.get("content")
    if not isinstance(content, str) or not content:
        content = "\n\n".join(str(c.get("text") or c.get("chunk_text") or "")
                              for c in document.get("chunks", []) if isinstance(c, dict))
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if isinstance(content, str) else None
    version = document.get("source_version") or document.get("version") or metadata.get("version") or document.get("last_updated")
    return {
        "source_version": str(version) if version is not None else None,
        "version": str(version) if version is not None else None,
        "version_id": document.get("version_id"),
        "content_hash": content_hash,
        "normalized_content_hash": content_hash,
        "source_content_hash": metadata.get("source_content_sha256") or document.get("source_content_hash"),
        "source_scope": document.get("source_scope") or metadata.get("source_scope") or "enterprise",
        "knowledge_base_id": document.get("knowledge_base_id") or metadata.get("knowledge_base_id") or metadata.get("space_id") or None,
        "document_id": metadata.get("page_id") or document.get("document_id") or document.get("doc_id"),
        "parser_version": metadata.get("parser_version") or metadata.get("renderer_version"),
        "chunker_version": metadata.get("chunker_version"),
        "sync_status": metadata.get("sync_status") or "unknown",
        "fetched_at": metadata.get("fetched_at"),
        "indexed_at": metadata.get("indexed_at"),
        "source_latest_checked_at": metadata.get("source_latest_checked_at"),
        "source_modified_at": metadata.get("last_updated") or document.get("last_updated"),
        "index_generation": metadata.get("index_generation"),
    }


def check_expected_source(document: dict[str, Any], *, expected_version=None, expected_hash=None) -> None:
    actual = source_metadata(document)
    if expected_version is not None and str(expected_version) != actual["source_version"]:
        raise DocumentVersionConflict(DocumentVersionConflict.code)
    if expected_hash is not None and expected_hash != actual["content_hash"]:
        raise DocumentVersionConflict(DocumentVersionConflict.code)


def chunk_metadata(document: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    provenance = source_metadata(document)
    doc_id = str(document.get("doc_id") or "")
    text = str(chunk.get("text") or chunk.get("chunk_text") or "")
    chunk_id = str(chunk.get("chunk_id") or f"{doc_id}::chunk_{chunk.get('index', 0)}")
    excerpt_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    identity = "\x1f".join((doc_id, provenance["source_version"] or "", provenance["content_hash"] or "", chunk_id, excerpt_hash))
    locator = chunk.get("locator")
    if not isinstance(locator, dict):
        locator = {}
    locator = {**locator, "chunk_id": chunk_id}
    for key in ("section_path", "block_start", "block_end", "line_start", "line_end"):
        if chunk.get(key) is not None:
            locator[key] = chunk[key]
    return {
        **provenance,
        "evidence_ref": "ev_" + hashlib.sha256(identity.encode()).hexdigest()[:32],
        "locator": locator,
        "excerpt_hash": excerpt_hash,
        "read_status": "original_excerpt_loaded",
        "read_at": datetime.now(timezone.utc).isoformat(),
    }
