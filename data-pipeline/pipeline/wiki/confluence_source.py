"""Authoritative Confluence input adapter for Wiki builds."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from confluence_export import ConfluencePage, ConfluenceStorageRenderer
from models.document import Document
from parsers.markdown_parser import MarkdownParser

from ..chunker import chunk_from_blocks
from ..confluence_snapshot import ConfluenceSnapshot
from ..structure import build_document_sections


def load_authoritative_confluence_document(snapshot: ConfluenceSnapshot) -> Document:
    """Re-render stored XHTML and accept only its exact Markdown derivative."""
    if snapshot.storage_path is None:
        raise ValueError(
            f"missing authoritative Confluence storage XHTML: {snapshot.metadata_path}"
        )
    metadata = json.loads(snapshot.metadata_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid Confluence metadata object: {snapshot.metadata_path}")
    storage = snapshot.storage_path.read_text(encoding="utf-8")
    parsed_url = urlparse(str(metadata.get("source_url") or ""))
    base_url = (
        f"{parsed_url.scheme}://{parsed_url.netloc}/wiki"
        if parsed_url.netloc
        else "https://localhost/wiki"
    )
    page = ConfluencePage(
        page_id=snapshot.page_id,
        title=str(metadata.get("title") or snapshot.page_id),
        space_id=snapshot.space_id,
        parent_id=str(metadata.get("parent_id") or ""),
        parent_type=str(metadata.get("parent_type") or "page"),
        position=0,
        version=snapshot.version,
        last_updated=str(metadata.get("last_updated") or ""),
        source_url=str(metadata.get("source_url") or ""),
        storage_html=storage,
    )
    rendered = ConfluenceStorageRenderer(base_url=base_url, page=page).render().markdown
    stored = snapshot.markdown_path.read_text(encoding="utf-8-sig")
    if rendered != stored:
        raise ValueError(
            "Confluence Markdown is not derived from authoritative XHTML: "
            f"{snapshot.markdown_path}"
        )
    document = MarkdownParser().parse_text(
        rendered,
        source=str(snapshot.markdown_path),
        metadata=metadata,
    )
    document.chunks = chunk_from_blocks(
        document.content_blocks,
        document.version_id,
        document_title=document.title,
    )
    document.sections = build_document_sections(document)
    return document
