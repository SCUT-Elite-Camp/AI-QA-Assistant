"""Retract Confluence documents from the original RAG projection and indexes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.confluence_snapshot import complete_confluence_export_pages


@dataclass(frozen=True)
class Retraction:
    document_id: str
    path: Path


def pending_confluence_retractions(
    documents_dir: str | Path, export_dir: str | Path,
) -> list[Retraction]:
    """Select only indexed documents omitted by a successful full export."""
    pending: list[Retraction] = []
    for retraction in withdrawn_confluence_documents(documents_dir, export_dir):
        raw = json.loads(retraction.path.read_text(encoding="utf-8"))
        metadata = raw.get("metadata") or {}
        if raw.get("active_version", True) is not False or metadata.get("rag_retraction_pending"):
            pending.append(retraction)
    return pending


def withdrawn_confluence_documents(
    documents_dir: str | Path, export_dir: str | Path,
) -> list[Retraction]:
    """List every omitted Confluence projection, including completed tombstones."""
    complete_pages = complete_confluence_export_pages(export_dir)
    withdrawn: list[Retraction] = []
    for path in sorted(Path(documents_dir).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"invalid RAG document projection: {path}")
        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid RAG document metadata: {path}")
        space_id = str(metadata.get("space_id") or "").strip()
        if space_id not in complete_pages:
            continue
        page_id = str(metadata.get("page_id") or "").strip()
        if not page_id:
            raise ValueError(f"Confluence document has no page ID: {path}")
        if page_id in complete_pages[space_id]:
            continue
        document_id = str(raw.get("doc_id") or "").strip()
        if document_id != path.stem:
            raise ValueError(f"RAG document path and ID differ: {path}")
        withdrawn.append(Retraction(document_id, path))
    return withdrawn


def mark_retraction_pending(retraction: Retraction) -> None:
    """Hide the old source before touching slower external indexes."""
    raw = json.loads(retraction.path.read_text(encoding="utf-8"))
    metadata = dict(raw.get("metadata") or {})
    raw["active_version"] = False
    metadata["rag_retraction_pending"] = True
    raw["metadata"] = metadata
    _atomic_write(retraction.path, raw)


def finish_retraction(retraction: Retraction) -> None:
    """Clear the pending marker after both indexes were updated."""
    raw = json.loads(retraction.path.read_text(encoding="utf-8"))
    metadata = dict(raw.get("metadata") or {})
    if raw.get("active_version") is not False:
        raise ValueError("cannot finish an active RAG document retraction")
    metadata.pop("rag_retraction_pending", None)
    raw["metadata"] = metadata
    _atomic_write(retraction.path, raw)


def _atomic_write(path: Path, raw: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
