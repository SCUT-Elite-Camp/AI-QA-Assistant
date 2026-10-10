from __future__ import annotations

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from data_persistence.wiki import WikiStore
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


class CountingStore(FakeStore):
    def __init__(self) -> None:
        self.search_calls = []
        self.page_calls = []
        self.source_calls = []

    def search_pages(self, query, **kwargs):
        self.search_calls.append({"query": query, **kwargs})
        return []

    def read_sources(self, page_id, **kwargs):
        self.source_calls.append({"page_id": page_id, **kwargs})
        return super().read_sources(page_id, **kwargs)

    def read_page(self, page_ref, **kwargs):
        self.page_calls.append({"page_ref": page_ref, **kwargs})
        return super().read_page(page_ref, **kwargs)


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


def test_personal_wiki_scope_is_isolated_between_overlapping_requests() -> None:
    barrier = Barrier(2)

    class ScopeStore(FakeStore):
        def search_pages(self, query, **kwargs):
            return [{"owner_id": kwargs["owner_id"], "knowledge_base_id": kwargs["knowledge_base_id"]}]

    tool = WikiSearchTool(ScopeStore())
    secret = "test-secret"

    def search_as(owner_id: str, knowledge_base_id: str) -> dict:
        token = hmac.new(
            secret.encode(),
            f"{owner_id}:{knowledge_base_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        tool.set_personal_context(owner_id, knowledge_base_id, token, secret=secret)
        barrier.wait(timeout=2)
        return tool.execute(query="RAG", source_scope="personal")["pages"][0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        alice = pool.submit(search_as, "alice", "alice-kb")
        bob = pool.submit(search_as, "bob", "bob-kb")

    assert alice.result(timeout=2) == {"owner_id": "alice", "knowledge_base_id": "alice-kb"}
    assert bob.result(timeout=2) == {"owner_id": "bob", "knowledge_base_id": "bob-kb"}


def test_invalid_wiki_signature_clears_only_current_request_context() -> None:
    tool = WikiSearchTool(FakeStore())
    secret = "test-secret"
    token = hmac.new(secret.encode(), b"alice:personal-kb", hashlib.sha256).hexdigest()
    tool.set_personal_context("alice", "personal-kb", token, secret=secret)

    other_request = ThreadPoolExecutor(max_workers=1)

    def invalid_context_result():
        tool.set_personal_context("mallory", "other-kb", "invalid", secret=secret)
        return tool.execute(query="RAG", source_scope="personal")

    try:
        assert other_request.submit(invalid_context_result).result(timeout=2)["pages"] == []
    finally:
        other_request.shutdown(wait=True)

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


@pytest.mark.parametrize("top_k", [True, False, "5", 1.5, 0, 13])
def test_wiki_page_search_rejects_invalid_top_k_before_store_search(top_k):
    store = CountingStore()
    tool = WikiSearchTool(store, enterprise_knowledge_base_id="kb")

    result = tool.execute(query="runtime", top_k=top_k)

    assert result == {
        "error": "invalid_wiki_query", "pages": [], "citation_authority": False,
    }
    assert store.search_calls == []


@pytest.mark.parametrize("top_k", [True, False, "5", 1.5, 0, 21])
@pytest.mark.parametrize("scope", ["enterprise", "personal"])
def test_wiki_evidence_rejects_invalid_top_k_before_store_or_retrieval(
    top_k, scope
):
    store = CountingStore()
    search = FakeSearchTool()
    library = FakeLibraryTool()
    tool = WikiSearchEvidenceTool(
        store, search, library, enterprise_knowledge_base_id="kb",
    )
    if scope == "personal":
        secret = "test-secret"
        token = hmac.new(
            secret.encode(), b"alice:personal-kb", hashlib.sha256,
        ).hexdigest()
        tool.set_personal_context("alice", "personal-kb", token, secret=secret)

    result = tool.execute(
        query="runtime", page_id="page-1", source_scope=scope, top_k=top_k,
    )

    assert result == {
        "error": "invalid_wiki_query", "items": [], "citation_authority": True,
    }
    assert store.source_calls == []
    assert search.calls == []
    assert library.calls == []


def test_wiki_top_k_defaults_and_integer_boundaries_are_preserved():
    store = CountingStore()
    page_search = WikiSearchTool(store, enterprise_knowledge_base_id="kb")
    page_search.execute(query="runtime")
    page_search.execute(query="runtime", top_k=1)
    page_search.execute(query="runtime", top_k=12)
    assert [call["top_k"] for call in store.search_calls] == [8, 1, 12]

    search = FakeSearchTool()
    evidence = WikiSearchEvidenceTool(
        store, search, enterprise_knowledge_base_id="kb",
    )
    evidence.execute(query="runtime", page_id="page-1")
    evidence.execute(query="runtime", page_id="page-1", top_k=1)
    evidence.execute(query="runtime", page_id="page-1", top_k=20)
    assert [call["top_k"] for call in search.calls] == [10, 1, 20]


@pytest.mark.parametrize("mode", [None, True, 1, "", "dense", [], {}])
@pytest.mark.parametrize("scope", ["enterprise", "personal"])
def test_wiki_evidence_rejects_invalid_mode_before_store_or_retrieval(mode, scope):
    store = CountingStore()
    search = FakeSearchTool()
    library = FakeLibraryTool()
    tool = WikiSearchEvidenceTool(
        store, search, library, enterprise_knowledge_base_id="kb",
    )
    if scope == "personal":
        secret = "test-secret"
        token = hmac.new(
            secret.encode(), b"alice:personal-kb", hashlib.sha256,
        ).hexdigest()
        tool.set_personal_context("alice", "personal-kb", token, secret=secret)

    result = tool.execute(
        query="runtime", page_id="page-1", source_scope=scope, mode=mode,
    )

    assert result == {
        "error": "invalid_wiki_query", "items": [], "citation_authority": True,
    }
    assert store.source_calls == []
    assert search.calls == []
    assert library.calls == []


def test_wiki_evidence_preserves_default_and_valid_modes():
    store = CountingStore()
    search = FakeSearchTool()
    evidence = WikiSearchEvidenceTool(
        store, search, enterprise_knowledge_base_id="kb",
    )
    evidence.execute(query="runtime", page_id="page-1")
    for mode in ("hybrid", "vector", "bm25"):
        evidence.execute(query="runtime", page_id="page-1", mode=mode)

    assert [call["mode"] for call in search.calls] == [
        "hybrid", "hybrid", "vector", "bm25",
    ]

    secret = "test-secret"
    token = hmac.new(
        secret.encode(), b"alice:personal-kb", hashlib.sha256,
    ).hexdigest()
    personal_library = FakeLibraryTool()
    personal_evidence = WikiSearchEvidenceTool(
        store, search, personal_library,
    )
    personal_evidence.set_personal_context(
        "alice", "personal-kb", token, secret=secret,
    )
    personal_evidence.execute(
        query="runtime", page_id="page-1", source_scope="personal",
    )
    for mode in ("hybrid", "vector", "bm25"):
        personal_evidence.execute(
            query="runtime", page_id="page-1", source_scope="personal", mode=mode,
        )

    assert [call["mode"] for call in personal_library.calls] == [
        "hybrid", "hybrid", "vector", "bm25",
    ]


@pytest.mark.parametrize("source_scope", [None, "", False, 1, "invalid", []])
def test_wiki_tools_reject_invalid_scope_before_storage_or_retrieval(source_scope):
    store = CountingStore()
    search = FakeSearchTool()
    library = FakeLibraryTool()
    tools = [
        (WikiSearchTool(store, enterprise_knowledge_base_id="kb"), "pages"),
        (WikiReadPageTool(store, enterprise_knowledge_base_id="kb"), "page"),
        (WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb"), "sources"),
        (
            WikiSearchEvidenceTool(
                store, search, library, enterprise_knowledge_base_id="kb",
            ),
            "items",
        ),
    ]

    for tool, empty_field in tools:
        result = tool.execute(
            query="runtime", page_id="page-1", page_ref="page-1",
            source_scope=source_scope,
        )
        assert result["error"] == "invalid_wiki_query"
        if empty_field == "page":
            assert result[empty_field] is None
        else:
            assert result[empty_field] == []

    assert store.search_calls == []
    assert store.page_calls == []
    assert store.source_calls == []
    assert search.calls == []
    assert library.calls == []


@pytest.mark.parametrize("query", [None, 1, True, [], {}, "", "   "])
def test_wiki_search_rejects_invalid_query_before_store_search(query):
    store = CountingStore()
    tool = WikiSearchTool(store, enterprise_knowledge_base_id="kb")

    result = tool.execute(query=query)

    assert result == {
        "error": "invalid_wiki_query", "pages": [], "citation_authority": False,
    }
    assert store.search_calls == []


@pytest.mark.parametrize("query", [None, 1, True, [], {}, "", "   "])
@pytest.mark.parametrize("scope", ["enterprise", "personal"])
def test_wiki_evidence_rejects_invalid_query_before_storage_or_retrieval(
    query, scope
):
    store = CountingStore()
    search = FakeSearchTool()
    library = FakeLibraryTool()
    tool = WikiSearchEvidenceTool(
        store, search, library, enterprise_knowledge_base_id="kb",
    )
    if scope == "personal":
        secret = "test-secret"
        token = hmac.new(
            secret.encode(), b"alice:personal-kb", hashlib.sha256,
        ).hexdigest()
        tool.set_personal_context("alice", "personal-kb", token, secret=secret)

    result = tool.execute(
        query=query, page_id="page-1", source_scope=scope,
    )

    assert result == {
        "error": "invalid_wiki_query", "items": [], "citation_authority": True,
    }
    assert store.source_calls == []
    assert search.calls == []
    assert library.calls == []


def test_wiki_search_paths_preserve_valid_string_query_behavior():
    store = CountingStore()
    page_search = WikiSearchTool(store, enterprise_knowledge_base_id="kb")
    page_search.execute(query=" runtime ")
    assert store.search_calls[0]["query"] == " runtime "

    search = FakeSearchTool()
    evidence = WikiSearchEvidenceTool(
        store, search, enterprise_knowledge_base_id="kb",
    )
    evidence.execute(query=" runtime ", page_id="page-1")
    assert search.calls[0]["query"] == "runtime"


@pytest.mark.parametrize("identifier", [None, 123, True, [], "", "   "])
def test_wiki_page_identifiers_reject_malformed_values_before_storage(
    identifier,
):
    store = CountingStore()
    search = FakeSearchTool()
    library = FakeLibraryTool()
    read_page = WikiReadPageTool(store, enterprise_knowledge_base_id="kb")
    read_sources = WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb")
    evidence = WikiSearchEvidenceTool(
        store, search, library, enterprise_knowledge_base_id="kb",
    )

    assert read_page.execute(page_ref=identifier)["error"] == "invalid_wiki_query"
    assert read_sources.execute(page_id=identifier)["error"] == "invalid_wiki_query"
    assert evidence.execute(
        query="runtime", page_id=identifier,
    )["error"] == "invalid_wiki_query"
    assert store.page_calls == []
    assert store.source_calls == []
    assert search.calls == []
    assert library.calls == []


@pytest.mark.parametrize("claim_id", [None, 123, True, []])
def test_wiki_claim_id_rejects_explicit_non_strings_before_storage(claim_id):
    store = CountingStore()
    search = FakeSearchTool()
    evidence = WikiSearchEvidenceTool(
        store, search, enterprise_knowledge_base_id="kb",
    )
    read_sources = WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb")

    assert read_sources.execute(
        page_id="page-1", claim_id=claim_id,
    )["error"] == "invalid_wiki_query"
    assert evidence.execute(
        query="runtime", page_id="page-1", claim_id=claim_id,
    )["error"] == "invalid_wiki_query"
    assert store.source_calls == []
    assert search.calls == []


def test_wiki_identifier_schemas_and_empty_claim_default_are_preserved():
    read_page_schema = WikiReadPageTool(FakeStore()).parameters["properties"]["page_ref"]
    read_sources_schema = WikiReadSourcesTool(FakeStore()).parameters["properties"]
    evidence_schema = WikiSearchEvidenceTool(
        FakeStore(), FakeSearchTool(), enterprise_knowledge_base_id="kb",
    ).parameters["properties"]

    assert read_page_schema["minLength"] == 1
    assert read_sources_schema["page_id"]["minLength"] == 1
    assert evidence_schema["page_id"]["minLength"] == 1
    assert read_sources_schema["claim_id"]["default"] == ""

    store = CountingStore()
    tool = WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb")
    tool.execute(page_id="page-1")
    tool.execute(page_id="page-1", claim_id="")
    assert [call["claim_id"] for call in store.source_calls] == ["", ""]
