from __future__ import annotations

import hashlib
import json

import pytest

from confluence_export import ConfluencePage, ConfluenceStorageRenderer
from pipeline.confluence_snapshot import ConfluenceSnapshot
from pipeline.wiki.confluence_source import load_authoritative_confluence_document


def _snapshot(tmp_path) -> ConfluenceSnapshot:
    page_dir = tmp_path / "page"
    page_dir.mkdir()
    storage = "<h1>Architecture</h1><p>The Agent uses bounded tool execution.</p>"
    page = ConfluencePage(
        page_id="42", title="Agent Design", space_id="RAG", parent_id="",
        parent_type="page", position=0, version=3, last_updated="",
        source_url="https://example.atlassian.net/wiki/spaces/RAG/pages/42",
        storage_html=storage,
    )
    markdown = ConfluenceStorageRenderer(
        base_url="https://example.atlassian.net/wiki", page=page,
    ).render().markdown
    markdown_path = page_dir / "index.md"
    storage_path = page_dir / "page.storage.xhtml"
    metadata_path = page_dir / "page.meta.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    storage_path.write_text(storage, encoding="utf-8")
    metadata_path.write_text(json.dumps({
        "space_id": "RAG", "page_id": "42", "version": 3,
        "title": "Agent Design", "source_url": page.source_url,
    }), encoding="utf-8")
    return ConfluenceSnapshot(
        markdown_path=markdown_path,
        storage_path=storage_path,
        metadata_path=metadata_path,
        section_tree_path=None,
        space_id="RAG",
        page_id="42",
        version=3,
        content_sha256=hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
        source_content_sha256=hashlib.sha256(storage_path.read_bytes()).hexdigest(),
    )


def test_wiki_confluence_adapter_rebuilds_document_from_authoritative_xhtml(tmp_path) -> None:
    document = load_authoritative_confluence_document(_snapshot(tmp_path))
    assert document.title == "Agent Design"
    assert document.chunks
    assert document.sections
    assert "bounded tool execution" in document.content


def test_wiki_confluence_adapter_rejects_markdown_not_derived_from_xhtml(tmp_path) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.markdown_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="not derived from authoritative XHTML"):
        load_authoritative_confluence_document(snapshot)
