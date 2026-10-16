import hashlib
import hmac

import pytest

from tool_layer.search_library_tool import SearchLibraryTool


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

    def fake_open(payload):
        captured.update(payload)
        return {"items": []}

    monkeypatch.setattr("tool_layer.search_library_tool.search_library_evidence", fake_open)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    tool.execute(
        query="risk", mode="bm25", doc_ids=["doc-from-model"],
    )

    assert captured["owner_id"] == "user-a"
    assert captured["knowledge_base_id"] == "kb-a"
    assert captured["doc_ids"] == ["doc-from-model"]
    assert set(captured) == {
        "owner_id", "knowledge_base_id", "query", "top_k", "mode", "doc_ids",
    }


def test_invalid_context_fails_closed(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", "0" * 64)
    assert tool.execute(query="secret") == {"error": "library_context_unavailable", "items": []}


def test_invalid_model_arguments_fail_before_backend(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
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
    embedder = ModuleType("pipeline.indexing.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.indexing.embedder", embedder)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert tool.execute(query="risk", mode=mode)["error"] == "invalid_library_query"
    assert embeddings == []
    assert calls == []


@pytest.mark.parametrize("query", [None, 1, True, ["risk"]])
def test_non_string_queries_fail_before_embedding_or_network(monkeypatch, query):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    import sys
    from types import ModuleType

    embeddings = []
    embedder = ModuleType("pipeline.indexing.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.indexing.embedder", embedder)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert tool.execute(query=query)["error"] == "invalid_library_query"
    assert embeddings == []
    assert calls == []


def test_oversized_search_queries_fail_before_embedding_or_network(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    embeddings = []
    import sys
    from types import ModuleType

    embedder = ModuleType("pipeline.indexing.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.indexing.embedder", embedder)
    requests = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )
    oversized_query = "x" * 4001

    assert tool.execute(query=oversized_query)["error"] == "invalid_library_query"
    assert embeddings == []
    assert requests == []


def test_max_length_search_queries_are_forwarded(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    captured = []

    def fake_open(payload):
        captured.append(payload)
        return {"items": []}

    monkeypatch.setattr("tool_layer.search_library_tool.search_library_evidence", fake_open)
    query = "x" * 4000

    tool.execute(query=query, mode="bm25")

    assert [len(payload["query"]) for payload in captured] == [4000]


def _authenticated_tool(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    return tool


def test_top_k_rejects_coercion_and_out_of_range_values_before_backend(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    for top_k in ("6", 1.5, True, 0, 21, None):
        assert tool.execute(query="risk", top_k=top_k)["error"] == "invalid_library_query"


    assert calls == []


def test_top_k_defaults_and_schema_boundaries_are_preserved(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    captured = []

    def fake_open(payload):
        captured.append(payload)
        return {"items": []}

    monkeypatch.setattr("tool_layer.search_library_tool.search_library_evidence", fake_open)

    tool.execute(query="risk")
    tool.execute(query="risk", top_k=1)
    tool.execute(query="risk", top_k=20)

    assert [payload["top_k"] for payload in captured] == [
        5, 1, 20,
    ]


def test_mode_defaults_and_valid_values_are_preserved(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    captured = []

    def fake_open(payload):
        captured.append(payload)
        return {"items": []}

    monkeypatch.setattr("tool_layer.search_library_tool.search_library_evidence", fake_open)

    tool.execute(query="risk")
    for mode in ("hybrid", "vector", "bm25"):
        tool.execute(query="risk", mode=mode)

    assert [payload["mode"] for payload in captured] == [
        "hybrid", "hybrid", "vector", "bm25",
    ]


def test_identifier_lists_reject_non_string_members_before_backend(monkeypatch):
    tool = _authenticated_tool(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "tool_layer.search_library_tool.search_library_evidence",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    for values in ([123], ["doc-a", 123], [None], [True]):
        assert tool.execute(query="risk", doc_ids=values)["error"] == "invalid_library_query"

    assert calls == []
