"""Retract Confluence documents from the original RAG projection and indexes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.confluence.snapshot import complete_confluence_export_pages


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
    complete_attachments = {}
    for manifest_path in sorted(Path(export_dir).glob("*/attachments-manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "ok" or manifest.get("full_sync") is not True:
            continue
        space = str(manifest.get("space_id") or "").strip()
        attachments = manifest.get("attachments")
        if not space or not isinstance(attachments, dict) or space in complete_attachments:
            raise ValueError(f"invalid complete attachment manifest: {manifest_path}")
        complete_attachments[space] = set(attachments)
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
        attachment_id = str(metadata.get("attachment_id") or "").strip()
        page_present = page_id in complete_pages[space_id]
        attachment_present = (
            not attachment_id or space_id not in complete_attachments
            or attachment_id in complete_attachments[space_id]
        )
        if page_present and attachment_present:
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
    metadata["sync_status"] = "quarantined"
    metadata["source_visibility"] = "not_visible"
    metadata["deletion_confirmed"] = False
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
