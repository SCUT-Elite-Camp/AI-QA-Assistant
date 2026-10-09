from __future__ import annotations

import json
import hashlib
import hmac
from pathlib import Path
from unittest.mock import patch

import pytest

from tool_layer.navigation_tools import BrowseDocumentOutlineTool, SearchEvidenceInScopeTool
from tool_layer.search_tool import RetrievalParameterError, SearchTool
from tool_layer.search_library_tool import SearchLibraryTool


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


def _search_tool(documents_dir: Path) -> SearchTool:
    rows = [
        {"doc_id": "doc_1", "chunk_id": "c1", "chunk_index": 0, "text": "overview", "score": 0.5},
        {"doc_id": "doc_1", "chunk_id": "c2", "chunk_index": 1, "text": "tool routing implementation", "score": 0.9},
    ]
    tool = SearchTool(backend=ScopedBackend(rows), documents_dir=str(documents_dir))
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
    assert search.backend.calls[-1]["filters"]["chunk_ids"] == ["c2"]


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


def test_enterprise_navigation_rejects_invalid_identifier_arrays_before_search(
    tmp_path: Path,
):
    search = _search_tool(tmp_path)
    calls = []
    search.browse_document_outline = lambda *args, **kwargs: calls.append((args, kwargs))
    search.search_evidence_in_scope = lambda *args, **kwargs: calls.append((args, kwargs))
    browse = BrowseDocumentOutlineTool(search)
    scoped = SearchEvidenceInScopeTool(search)

    for doc_ids in (["doc"] * 101, ["doc", 1], "doc"):
        result = browse.execute(query="routing", doc_ids=doc_ids)
        assert result["error"] == "invalid_navigation_query"
        assert result["sections"] == []

    invalid_scoped_args = [
        {"section_ids": []},
        {"section_ids": ["section"] * 21},
        {"section_ids": ["section", 1]},
        {"section_ids": ["section"], "doc_ids": ["doc"] * 101},
        {"section_ids": ["section"], "doc_ids": ["doc", 1]},
    ]
    for arguments in invalid_scoped_args:
        result = scoped.execute(query="routing", **arguments)
        assert result["error"] == "invalid_navigation_query"
        assert result["items"] == []

    assert calls == []


def test_enterprise_navigation_accepts_100_documents_and_20_sections_unchanged(
    tmp_path: Path,
):
    search = _search_tool(tmp_path)
    captured = {}

    def browse(query, *, doc_ids, top_k):
        captured["browse"] = {"query": query, "doc_ids": doc_ids, "top_k": top_k}
        return []

    def scoped(query, *, section_ids, doc_ids, top_k, mode):
        captured["scoped"] = {
            "query": query,
            "section_ids": section_ids,
            "doc_ids": doc_ids,
            "top_k": top_k,
            "mode": mode,
        }
        return []

    search.browse_document_outline = browse
    search.search_evidence_in_scope = scoped
    document_ids = [f"doc-{index}" for index in range(100)]
    section_ids = [f"section-{index}" for index in range(20)]

    assert BrowseDocumentOutlineTool(search).execute(
        query="routing", doc_ids=document_ids
    )["sections"] == []
    assert SearchEvidenceInScopeTool(search).execute(
        query="routing", section_ids=section_ids, doc_ids=document_ids
    )["items"] == []

    assert captured["browse"]["doc_ids"] is document_ids
    assert captured["scoped"]["section_ids"] is section_ids
    assert captured["scoped"]["doc_ids"] is document_ids


def test_enterprise_navigation_rejects_invalid_top_k_before_search(tmp_path: Path):
    search = _search_tool(tmp_path)
    calls = []
    search.browse_document_outline = lambda *args, **kwargs: calls.append((args, kwargs))
    search.search_evidence_in_scope = lambda *args, **kwargs: calls.append((args, kwargs))
    browse = BrowseDocumentOutlineTool(search)
    scoped = SearchEvidenceInScopeTool(search)

    for top_k in (True, False, "5", 1.5, 0, 13):
        result = browse.execute(query="routing", top_k=top_k)
        assert result["error"] == "invalid_navigation_query"

    for top_k in (True, False, "5", 1.5, 0, 21):
        result = scoped.execute(
            query="routing", section_ids=["section"], top_k=top_k
        )
        assert result["error"] == "invalid_navigation_query"

    assert calls == []


@pytest.mark.parametrize("source_scope", [None, "", False, 1, "invalid", []])
def test_navigation_rejects_invalid_source_scope_before_either_route(
    tmp_path: Path, source_scope
):
    search = _search_tool(tmp_path)
    retrieval_calls = []
    search.browse_document_outline = lambda *args, **kwargs: retrieval_calls.append((args, kwargs))
    search.search_evidence_in_scope = lambda *args, **kwargs: retrieval_calls.append((args, kwargs))

    class PersonalLibrary:
        def browse_outline(self, **kwargs):
            retrieval_calls.append(kwargs)

        def search_evidence_in_scope(self, **kwargs):
            retrieval_calls.append(kwargs)

    browse = BrowseDocumentOutlineTool(search, PersonalLibrary())
    scoped = SearchEvidenceInScopeTool(search, PersonalLibrary())

    assert browse.execute(query="routing", source_scope=source_scope)["error"] == (
        "invalid_navigation_query"
    )
    assert scoped.execute(
        query="routing", section_ids=["section"], source_scope=source_scope,
    )["error"] == "invalid_navigation_query"
    assert retrieval_calls == []


@pytest.mark.parametrize("query", [None, 1, True, ["routing"]])
@pytest.mark.parametrize("source_scope", ["enterprise", "personal"])
def test_navigation_rejects_non_string_query_before_either_route(
    tmp_path: Path, query, source_scope
):
    search = _search_tool(tmp_path)
    calls = []
    search.browse_document_outline = lambda *args, **kwargs: calls.append((args, kwargs))
    search.search_evidence_in_scope = lambda *args, **kwargs: calls.append((args, kwargs))

    class PersonalLibrary:
        def browse_outline(self, **kwargs):
            calls.append(kwargs)

        def search_evidence_in_scope(self, **kwargs):
            calls.append(kwargs)

    browse = BrowseDocumentOutlineTool(search, PersonalLibrary())
    scoped = SearchEvidenceInScopeTool(search, PersonalLibrary())
    assert browse.execute(query=query, source_scope=source_scope)["error"] == (
        "invalid_navigation_query"
    )
    assert scoped.execute(
        query=query, section_ids=["section"], source_scope=source_scope,
    )["error"] == "invalid_navigation_query"
    assert calls == []


@pytest.mark.parametrize("mode", [None, "", False, 1, "dense", []])
@pytest.mark.parametrize("source_scope", ["enterprise", "personal"])
def test_scoped_navigation_rejects_invalid_mode_before_either_route(
    tmp_path: Path, mode, source_scope
):
    search = _search_tool(tmp_path)
    calls = []
    search.search_evidence_in_scope = lambda *args, **kwargs: calls.append((args, kwargs))

    class PersonalLibrary:
        def search_evidence_in_scope(self, **kwargs):
            calls.append(kwargs)

    result = SearchEvidenceInScopeTool(search, PersonalLibrary()).execute(
        query="routing", section_ids=["section"], source_scope=source_scope,
        mode=mode,
    )

    assert result["error"] == "invalid_navigation_query"
    assert calls == []


def test_scoped_navigation_defaults_and_preserves_valid_modes(tmp_path: Path):
    search = _search_tool(tmp_path)
    enterprise_modes = []
    personal_modes = []
    search.search_evidence_in_scope = (
        lambda *args, **kwargs: enterprise_modes.append(kwargs["mode"]) or []
    )

    class PersonalLibrary:
        def search_evidence_in_scope(self, **kwargs):
            personal_modes.append(kwargs["mode"])
            return {"items": []}

    tool = SearchEvidenceInScopeTool(search, PersonalLibrary())
    tool.execute(query="routing", section_ids=["section"])
    for mode in ("hybrid", "vector", "bm25"):
        tool.execute(query="routing", section_ids=["section"], mode=mode)
    tool.execute(
        query="routing", section_ids=["section"], source_scope="personal",
    )
    for mode in ("hybrid", "vector", "bm25"):
        tool.execute(
            query="routing", section_ids=["section"],
            source_scope="personal", mode=mode,
        )

    assert enterprise_modes == ["hybrid", "hybrid", "vector", "bm25"]
    assert personal_modes == ["hybrid", "hybrid", "vector", "bm25"]


def test_personal_navigation_rejects_non_string_ids_like_enterprise(
    tmp_path: Path, monkeypatch
):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    library = SearchLibraryTool()
    library.set_request_context("user-a", "kb-a", token)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    tool = SearchEvidenceInScopeTool(_search_tool(tmp_path), library)

    for section_ids in ([123], ["section-a", 123], [None]):
        assert tool.execute(
            query="routing", source_scope="personal", section_ids=section_ids,
        )["error"] == "invalid_library_query"
    for doc_ids in ([123], ["doc-a", False]):
        assert tool.execute(
            query="routing", source_scope="personal",
            section_ids=["section-a"], doc_ids=doc_ids,
        )["error"] == "invalid_library_query"

    assert calls == []


def test_enterprise_navigation_preserves_top_k_defaults_and_boundaries(tmp_path: Path):
    search = _search_tool(tmp_path)
    captured = []
    search.browse_document_outline = lambda *args, **kwargs: captured.append(kwargs["top_k"]) or []
    search.search_evidence_in_scope = lambda *args, **kwargs: captured.append(kwargs["top_k"]) or []
    browse = BrowseDocumentOutlineTool(search)
    scoped = SearchEvidenceInScopeTool(search)

    browse.execute(query="routing")
    scoped.execute(query="routing", section_ids=["section"])
    for top_k in (1, 12):
        browse.execute(query="routing", top_k=top_k)
    for top_k in (1, 20):
        scoped.execute(query="routing", section_ids=["section"], top_k=top_k)

    assert captured == [8, 10, 1, 12, 1, 20]


def test_search_tool_scope_rejects_invalid_arrays_without_truncating():
    backend = ScopedBackend([])
    search = SearchTool(backend=backend)

    with patch.dict("os.environ", {"HIERARCHICAL_NAVIGATION_ENABLED": "true"}):
        with pytest.raises(RetrievalParameterError, match="section_ids"):
            search.search_evidence_in_scope(
                "routing", section_ids=["section"] * 21
            )
        with pytest.raises(RetrievalParameterError, match="section_ids"):
            search.search_evidence_in_scope("routing", section_ids=[""])
        with pytest.raises(RetrievalParameterError, match="doc_ids"):
            search.browse_document_outline(
                "routing", doc_ids=["doc"] * 101
            )

    assert backend.calls == []
