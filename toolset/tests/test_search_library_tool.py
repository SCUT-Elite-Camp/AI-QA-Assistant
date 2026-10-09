import hashlib
import hmac
import json

import pytest

from tool_layer.search_library_tool import SearchLibraryTool


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return b'{"items": []}'


def test_schema_does_not_expose_authorization_fields():
    properties = SearchLibraryTool().parameters["properties"]
    assert properties["query"]["minLength"] == 1
    assert properties["query"]["maxLength"] == 4000
    assert "owner_user_id" not in properties
    assert "knowledge_base_id" not in properties
    assert "source_scope" not in properties


def test_signed_context_is_injected_and_doc_ids_remain_scoped(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    captured = {}

    def fake_open(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    tool.execute(
        query="risk", mode="bm25", doc_ids=["doc-from-model"],
        navigation_mode="hierarchical",
    )

    assert captured["owner_id"] == "user-a"
    assert captured["knowledge_base_id"] == "kb-a"
    assert captured["doc_ids"] == ["doc-from-model"]
    assert set(captured) == {
        "owner_id", "knowledge_base_id", "query", "top_k", "mode", "doc_ids",
        "navigation_mode",
    }
    assert captured["navigation_mode"] == "direct"


def test_legacy_navigation_mode_is_never_forwarded_as_automatic_navigation(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    monkeypatch.setenv("HIERARCHICAL_NAVIGATION_ENABLED", "true")
    captured = {}

    def fake_open(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    tool.execute(query="risk", mode="bm25", navigation_mode="hierarchical")

    assert captured["navigation_mode"] == "direct"
    assert "navigation_mode" not in tool.parameters["properties"]


def test_invalid_context_fails_closed(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", "0" * 64)
    assert tool.execute(query="secret") == {"error": "library_context_unavailable", "items": []}


def test_invalid_model_arguments_fail_before_network(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)

    assert tool.execute(query="", mode="hybrid")["error"] == "invalid_library_query"
    assert tool.execute(query="risk", mode="invalid")["error"] == "invalid_library_query"
    assert tool.execute(query="risk", doc_ids=["x"] * 101)["error"] == "invalid_library_query"


@pytest.mark.parametrize("mode", [None, "", False, 1, "dense", []])
def test_invalid_explicit_mode_fails_before_embedding_or_network(monkeypatch, mode):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    import sys
    from types import ModuleType

    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert tool.execute(query="risk", mode=mode)["error"] == "invalid_library_query"
    assert tool.search_evidence_in_scope(
        query="risk", section_ids=["section-a"], mode=mode,
    )["error"] == "invalid_library_query"
    assert embeddings == []
    assert calls == []


@pytest.mark.parametrize("query", [None, 1, True, ["risk"]])
def test_non_string_queries_fail_before_embedding_or_network(monkeypatch, query):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    import sys
    from types import ModuleType

    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert tool.execute(query=query)["error"] == "invalid_library_query"
    assert tool.browse_outline(query=query)["error"] == "invalid_library_query"
    assert tool.search_evidence_in_scope(
        query=query, section_ids=["section-a"],
    )["error"] == "invalid_library_query"
    assert embeddings == []
    assert calls == []


def test_oversized_search_and_navigation_queries_fail_before_embedding_or_network(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    embeddings = []
    import sys
    from types import ModuleType

    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )
    oversized_query = "x" * 4001

    assert tool.execute(query=oversized_query)["error"] == "invalid_library_query"
    assert tool.browse_outline(query=oversized_query)["error"] == "invalid_library_query"
    assert tool.search_evidence_in_scope(
        query=oversized_query, section_ids=["section-a"]
    )["error"] == "invalid_library_query"
    assert embeddings == []
    assert requests == []


def test_max_length_search_and_navigation_queries_are_forwarded(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    captured = []

    def fake_open(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)
    query = "x" * 4000

    tool.execute(query=query, mode="bm25")
    tool.browse_outline(query=query)
    tool.search_evidence_in_scope(query=query, section_ids=["section-a"])

    assert [len(payload["query"]) for payload in captured] == [4000, 4000, 4000]


def _authenticated_tool(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    return tool


def test_navigation_normalizes_document_and_section_ids(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    captured = []

    def fake_open(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)

    tool.browse_outline(query="risk", doc_ids=[" doc-a "])
    tool.search_evidence_in_scope(
        query="risk",
        doc_ids=[" doc-b "],
        section_ids=[" section-a "],
    )

    assert captured[0]["doc_ids"] == ["doc-a"]
    assert captured[1]["doc_ids"] == ["doc-b"]
    assert captured[1]["section_ids"] == ["section-a"]


def test_navigation_defaults_are_operation_specific_and_explicit_values_are_preserved(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    captured = []

    def fake_open(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)

    tool.browse_outline(query="risk")
    tool.search_evidence_in_scope(query="risk", section_ids=["section-a"])
    tool.browse_outline(query="risk", top_k=6)
    tool.search_evidence_in_scope(
        query="risk", section_ids=["section-a"], top_k=4
    )

    assert [payload["top_k"] for payload in captured] == [8, 10, 6, 4]


def test_top_k_rejects_coercion_and_out_of_range_values_before_network(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    for top_k in ("6", 1.5, True, 0, 21, None):
        assert tool.execute(query="risk", top_k=top_k)["error"] == "invalid_library_query"
        assert tool.search_evidence_in_scope(
            query="risk", section_ids=["section-a"], top_k=top_k
        )["error"] == "invalid_library_query"

    for top_k in ("6", 1.5, True, 0, 13, None):
        assert tool.browse_outline(query="risk", top_k=top_k)["error"] == "invalid_library_query"

    assert calls == []


def test_top_k_defaults_and_schema_boundaries_are_preserved(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    captured = []

    def fake_open(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)

    tool.execute(query="risk")
    tool.browse_outline(query="risk")
    tool.search_evidence_in_scope(query="risk", section_ids=["section-a"])
    tool.execute(query="risk", top_k=1)
    tool.execute(query="risk", top_k=20)
    tool.browse_outline(query="risk", top_k=1)
    tool.browse_outline(query="risk", top_k=12)
    tool.search_evidence_in_scope(query="risk", section_ids=["section-a"], top_k=1)
    tool.search_evidence_in_scope(query="risk", section_ids=["section-a"], top_k=20)

    assert [payload["top_k"] for payload in captured] == [
        5, 8, 10, 1, 20, 1, 12, 1, 20,
    ]


def test_mode_defaults_and_valid_values_are_preserved(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    captured = []

    def fake_open(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)

    tool.execute(query="risk")
    tool.search_evidence_in_scope(query="risk", section_ids=["section-a"])
    for mode in ("hybrid", "vector", "bm25"):
        tool.execute(query="risk", mode=mode)
        tool.search_evidence_in_scope(
            query="risk", section_ids=["section-a"], mode=mode,
        )

    assert [payload["mode"] for payload in captured] == [
        "hybrid", "hybrid", "hybrid", "hybrid", "vector", "vector",
        "bm25", "bm25",
    ]


def test_navigation_rejects_malformed_ids_before_network(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    calls = []

    def fake_open(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("network called for invalid identifiers")

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)

    malformed_doc_ids = [["  "], ["x" * 129], ["doc"] * 101]
    for doc_ids in malformed_doc_ids:
        assert tool.browse_outline(query="risk", doc_ids=doc_ids)["error"] == "invalid_library_query"
        assert tool.search_evidence_in_scope(
            query="risk", doc_ids=doc_ids, section_ids=["section-a"]
        )["error"] == "invalid_library_query"

    malformed_section_ids = [[], ["  "], ["x" * 129], ["section"] * 21, "section-a"]
    for section_ids in malformed_section_ids:
        assert tool.search_evidence_in_scope(
            query="risk", section_ids=section_ids
        )["error"] == "invalid_library_query"

    assert calls == []


def test_identifier_lists_reject_non_string_members_before_network(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    for values in ([123], ["doc-a", 123], [None], [True]):
        assert tool.execute(query="risk", doc_ids=values)["error"] == "invalid_library_query"
        assert tool.browse_outline(query="risk", doc_ids=values)["error"] == "invalid_library_query"
        assert tool.search_evidence_in_scope(
            query="risk", section_ids=values,
        )["error"] == "invalid_library_query"
    for doc_ids in ([123], ["doc-a", False]):
        assert tool.search_evidence_in_scope(
            query="risk", section_ids=["section-a"], doc_ids=doc_ids,
        )["error"] == "invalid_library_query"

    assert calls == []
