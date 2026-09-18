from __future__ import annotations

import hashlib
import hmac

from storage.wiki_store import WikiStore
from tool_layer.wiki_tool import (
    WikiReadPageTool,
    WikiReadSourcesTool,
    WikiSearchEvidenceTool,
    WikiSearchTool,
)


class FakeStore:
    def search_pages(self, query, **kwargs):
        return [{"page_id": "page-1", "title": query, "evidence_ids": ["ev-1"], "citation_authority": False}]

    def read_page(self, page_ref, **kwargs):
        return {"id": page_ref, "title": "Topic", "citation_authority": False}

    def read_sources(self, page_id, **kwargs):
        return [{
            "claim_id": "claim-1", "document_id": "doc-1", "document_version_id": "ver-1",
            "section_id": "sec-1", "evidence_id": "ev-1", "support_quote": "not exposed",
        }]


class FakeSearchTool:
    def __init__(self) -> None:
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [{
            "doc_id": "doc-1", "chunk_id": "ev-1", "chunk_index": 0,
            "chunk_text": "Authoritative Evidence", "title": "Document",
            "score": 0.9, "version_id": "ver-1",
        }]


class FakeLibraryTool:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return {"items": [{
            "document_id": "doc-1", "version_id": "ver-1", "evidence_id": "ev-1",
            "content": "Personal Evidence", "filename": "notes.md", "score": 0.8,
        }]}


def test_enterprise_wiki_tools_expose_navigation_but_not_citation_authority() -> None:
    store = FakeStore()
    search = WikiSearchTool(store, enterprise_knowledge_base_id="kb")
    read = WikiReadPageTool(store, enterprise_knowledge_base_id="kb")
    sources = WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb")
    assert search.execute(query="RAG")["citation_authority"] is False
    assert read.execute(page_ref="page-1")["page"]["id"] == "page-1"
    result = sources.execute(page_id="page-1")
    assert result["sources"][0]["evidence_id"] == "ev-1"
    assert "support_quote" not in result["sources"][0]


def test_personal_wiki_tools_require_signed_request_context() -> None:
    tool = WikiSearchTool(FakeStore())
    assert tool.execute(query="RAG", source_scope="personal")["pages"] == []
    secret = "test-secret"
    token = hmac.new(secret.encode(), b"alice:personal-kb", hashlib.sha256).hexdigest()
    tool.set_personal_context("alice", "personal-kb", token, secret=secret)
    assert tool.execute(query="RAG", source_scope="personal")["pages"][0]["page_id"] == "page-1"


def test_enterprise_wiki_evidence_reuses_traditional_retriever_with_document_scope() -> None:
    search = FakeSearchTool()
    tool = WikiSearchEvidenceTool(
        FakeStore(), search, enterprise_knowledge_base_id="kb",
    )
    result = tool.execute(
        query="runtime", page_id="page-1", source_scope="enterprise",
        top_k=6, mode="hybrid",
    )

    assert result["citation_authority"] is True
    assert result["source_documents"] == 1
    assert result["items"][0]["source_scope"] == "enterprise"
    assert search.calls == [{
        "query": "runtime", "top_k": 6, "mode": "hybrid",
        "filters": {"doc_ids": ["doc-1"]},
    }]


def test_personal_wiki_evidence_requires_signed_scope_and_uses_library_search() -> None:
    library = FakeLibraryTool()
    tool = WikiSearchEvidenceTool(FakeStore(), FakeSearchTool(), library)
    assert tool.execute(
        query="runtime", page_id="page-1", source_scope="personal",
    )["items"] == []

    secret = "test-secret"
    token = hmac.new(secret.encode(), b"alice:personal-kb", hashlib.sha256).hexdigest()
    tool.set_personal_context("alice", "personal-kb", token, secret=secret)
    result = tool.execute(
        query="runtime", page_id="page-1", source_scope="personal", mode="bm25",
    )
    assert result["citation_authority"] is True
    assert library.calls == [{
        "query": "runtime", "top_k": 10, "mode": "bm25", "doc_ids": ["doc-1"],
    }]


def test_wiki_evidence_rejects_stale_versions_and_unrelated_documents() -> None:
    class MixedSearch(FakeSearchTool):
        def search(self, **kwargs):
            self.calls.append(kwargs)
            return [
                {"doc_id": "doc-1", "version_id": "old", "chunk_id": "old",
                 "chunk_text": "Stale content", "score": 0.9},
                {"doc_id": "other", "version_id": "ver-1", "chunk_id": "other",
                 "chunk_text": "Unrelated content", "score": 0.8},
                {"doc_id": "doc-1", "version_id": "ver-1", "chunk_id": "current",
                 "chunk_text": "Current Evidence", "score": 0.7},
            ]

    result = WikiSearchEvidenceTool(
        FakeStore(), MixedSearch(), enterprise_knowledge_base_id="kb",
    ).execute(query="runtime", page_id="page-1")
    assert [item["chunk_id"] for item in result["items"]] == ["current"]


def test_personal_wiki_evidence_rejects_wrong_library_version() -> None:
    class MixedLibrary(FakeLibraryTool):
        def execute(self, **kwargs):
            result = super().execute(**kwargs)
            result["items"].append({
                "document_id": "doc-1", "version_id": "old",
                "evidence_id": "stale", "content": "Stale Evidence",
            })
            return result

    tool = WikiSearchEvidenceTool(FakeStore(), FakeSearchTool(), MixedLibrary())
    secret = "test-secret"
    token = hmac.new(secret.encode(), b"alice:personal-kb", hashlib.sha256).hexdigest()
    tool.set_personal_context("alice", "personal-kb", token, secret=secret)
    result = tool.execute(query="runtime", page_id="page-1", source_scope="personal")
    assert [item["evidence_id"] for item in result["items"]] == ["ev-1"]
