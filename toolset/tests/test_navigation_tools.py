from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tool_layer.navigation_tools import BrowseDocumentOutlineTool, SearchEvidenceInScopeTool
from tool_layer.search_tool import SearchTool


class ScopedBackend:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def search(self, query, top_k, mode, filters=None):
        self.calls.append({"query": query, "top_k": top_k, "mode": mode, "filters": filters})
        allowed_docs = set((filters or {}).get("doc_ids") or [])
        allowed_chunks = set((filters or {}).get("chunk_ids") or [])
        return [
            row for row in self.rows
            if (not allowed_docs or row["doc_id"] in allowed_docs)
            and (not allowed_chunks or row["chunk_id"] in allowed_chunks)
        ][:top_k]


class EmptySectionIndex:
    def search(self, *args, **kwargs):
        return []


def _search_tool(documents_dir: Path) -> SearchTool:
    rows = [
        {"doc_id": "doc_1", "chunk_id": "c1", "chunk_index": 0, "text": "overview", "score": 0.5},
        {"doc_id": "doc_1", "chunk_id": "c2", "chunk_index": 1, "text": "tool routing implementation", "score": 0.9},
    ]
    tool = SearchTool(backend=ScopedBackend(rows), documents_dir=str(documents_dir))
    tool._section_bm25_index = EmptySectionIndex()
    return tool


def test_outline_is_navigation_only_and_scoped_search_returns_authoritative_chunks(tmp_path: Path) -> None:
    (tmp_path / "doc_1.json").write_text(json.dumps({
        "doc_id": "doc_1",
        "active_version": True,
        "title": "Architecture",
        "version_id": "ver_1",
        "chunks": [
            {"chunk_id": "c1", "index": 0, "text": "overview"},
            {"chunk_id": "c2", "index": 1, "text": "tool routing implementation"},
        ],
        "sections": [{
            "id": "sec_agent",
            "title": "Agent Layer",
            "section_path": ["Architecture", "Agent Layer"],
            "summary": "tool routing implementation",
            "navigation_text": "Architecture Agent Layer tool routing implementation",
            "evidence_ids": ["c2"],
            "quality": "high",
            "level": 1,
        }, {
            "id": "sec_runtime", "parent_id": "sec_agent",
            "title": "Runtime", "section_path": ["Architecture", "Agent Layer", "Runtime"],
            "summary": "bounded loop", "evidence_ids": ["c2"],
            "quality": "high", "level": 2, "ordinal": 2,
        }],
    }), encoding="utf-8")
    search = _search_tool(tmp_path)

    with patch.dict("os.environ", {"HIERARCHICAL_NAVIGATION_ENABLED": "true"}):
        outline = BrowseDocumentOutlineTool(search).execute(query="tool routing")
        scoped = SearchEvidenceInScopeTool(search).execute(
            query="tool routing",
            section_ids=["sec_agent"],
            mode="hybrid",
            top_k=5,
        )

    assert outline["citation_authority"] is False
    assert outline["sections"][0]["id"] == "sec_agent"
    assert outline["sections"][0]["navigation_relation"] == "matched"
    assert outline["sections"][1]["id"] == "sec_runtime"
    assert outline["sections"][1]["navigation_relation"] == "child"
    assert "score" not in outline["sections"][1]
    assert scoped["citation_authority"] is True
    assert [item["chunk_id"] for item in scoped["items"]] == ["c2"]
    assert scoped["items"][0]["matched_section_ids"] == ["sec_agent"]


def test_unknown_or_unauthorized_section_id_returns_no_evidence(tmp_path: Path) -> None:
    (tmp_path / "doc_1.json").write_text(json.dumps({
        "doc_id": "doc_1", "active_version": True, "sections": [{
            "id": "sec_agent", "title": "Agent", "section_path": ["Agent"],
            "summary": "routing", "evidence_ids": ["c2"], "quality": "high", "level": 1,
        }],
    }), encoding="utf-8")
    search = _search_tool(tmp_path)

    with patch.dict("os.environ", {"HIERARCHICAL_NAVIGATION_ENABLED": "true"}):
        result = SearchEvidenceInScopeTool(search).execute(
            query="routing", section_ids=["sec_other"], top_k=5,
        )

    assert result["items"] == []
