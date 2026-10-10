import sys
from types import ModuleType

import pytest

from tool_layer.attachment_tools import InspectAttachmentTool, SearchAttachmentsTool
from tool_layer.registry import ToolRegistry


def test_attachment_tools_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATTACHMENTS_ENABLED", raising=False)
    registry = ToolRegistry()
    assert registry.get_tool("search_attachments") is None
    assert registry.get_tool("inspect_attachment") is None


def test_attachment_tools_require_explicit_enable(monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ENABLED", "true")
    registry = ToolRegistry()
    assert registry.get_tool("search_attachments") is not None
    assert registry.get_tool("inspect_attachment") is not None


def test_search_attachment_schema_caps_query_length():
    query_schema = SearchAttachmentsTool().parameters["properties"]["query"]
    assert query_schema["minLength"] == 1
    assert query_schema["maxLength"] == 4000


def test_oversized_attachment_query_fails_before_embedding_or_request(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []
    monkeypatch.setattr(tool, "_request", lambda *args, **kwargs: requests.append((args, kwargs)))

    result = tool.execute(query="x" * 4001)

    assert result == {"error": "invalid_attachment_query", "items": []}
    assert embeddings == []
    assert requests == []


@pytest.mark.parametrize("top_k", [True, False, "5", 1.5, 0, 21, None])
def test_invalid_top_k_fails_before_embedding_or_request(monkeypatch, top_k):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []
    monkeypatch.setattr(
        tool, "_request", lambda *args, **kwargs: requests.append((args, kwargs))
    )

    result = tool.execute(query="risk", top_k=top_k)

    assert result == {"error": "invalid_attachment_query", "items": []}
    assert embeddings == []
    assert requests == []


@pytest.mark.parametrize("query", [None, True, False, 123, [], {}, "", "   "])
def test_invalid_query_fails_before_authorization_embedding_or_request(
    monkeypatch, query
):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []
    monkeypatch.setattr(
        tool, "_request", lambda *args, **kwargs: requests.append((args, kwargs))
    )

    result = tool.execute(query=query)

    assert result == {"error": "invalid_attachment_query", "items": []}
    assert embeddings == []
    assert requests == []


def test_top_k_default_and_integer_boundaries_are_forwarded(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    forwarded = []
    monkeypatch.setattr(
        tool,
        "_request",
        lambda _path, payload, **_kwargs: forwarded.append(payload["top_k"])
        or {"items": []},
    )

    tool.execute(query="risk")
    tool.execute(query="risk", top_k=1)
    tool.execute(query="risk", top_k=20)

    assert forwarded == [8, 1, 20]


def test_valid_attachment_query_is_forwarded_without_trimming(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    forwarded = []
    monkeypatch.setattr(
        tool,
        "_request",
        lambda _path, payload, **_kwargs: forwarded.append(payload["query"])
        or {"items": []},
    )

    assert tool.execute(query=" risk ") == {"items": []}
    assert forwarded == [" risk "]


def test_max_length_attachment_query_is_forwarded(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    requests = []
    monkeypatch.setattr(
        tool,
        "_request",
        lambda path, payload, **kwargs: requests.append((path, payload)) or {"items": []},
    )

    result = tool.execute(query="x" * 4000)

    assert result == {"items": []}
    assert len(requests[0][1]["query"]) == 4000


def test_search_prefers_selected_ids_without_leaving_allowlist(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_selected", "att_other"], ["att_selected"])
    calls = []

    def fake_request(path, payload, **_kwargs):
        calls.append((path, payload))
        attachment_id = payload["attachment_ids"][0]
        return {"items": [{
            "attachment_id": attachment_id,
            "evidence_id": f"aev_{len(calls)}",
            "content": attachment_id,
        }]}

    monkeypatch.setattr(tool, "_request", fake_request)
    result = tool.execute(query="risk", top_k=4)

    assert calls[0][1]["attachment_ids"] == ["att_selected", "att_other"]
    assert calls[1][1]["attachment_ids"] == ["att_selected"]
    assert result["items"][0]["attachment_id"] == "att_selected"


@pytest.mark.parametrize(
    "unavailable_reason",
    ["missing_context", "empty_allowlist", "missing_secret"],
)
def test_unavailable_attachment_search_skips_embedding_and_request(
    monkeypatch, unavailable_reason
):
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchAttachmentsTool()
    if unavailable_reason == "empty_allowlist":
        tool.set_request_context([], [])
    elif unavailable_reason == "missing_secret":
        tool.set_request_context(["att_allowed"], [])
        monkeypatch.delenv("ATTACHMENT_INTERNAL_SECRET")

    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts))
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []
    monkeypatch.setattr(
        tool,
        "_request",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )

    result = tool.execute(query="find risk", top_k=4)

    assert result == {"error": "attachments_unavailable", "items": []}
    assert embeddings == []
    assert requests == []


def test_authorized_vector_search_embeds_and_forwards_vector(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], [])
    embeddings = []
    embedder = ModuleType("pipeline.embedder")
    embedder.embed_texts = lambda texts: embeddings.append(list(texts)) or [[0.1, 0.2]]
    monkeypatch.setitem(sys.modules, "pipeline.embedder", embedder)
    requests = []

    def fake_request(path, payload, **_kwargs):
        requests.append((path, payload))
        return {"items": [{"attachment_id": "att_allowed", "evidence_id": "aev_1"}]}

    monkeypatch.setattr(tool, "_request", fake_request)

    result = tool.execute(query="find risk", top_k=4)

    assert embeddings == [["find risk"]]
    assert requests[0][1]["query_vector"] == [0.1, 0.2]
    assert result["items"][0]["attachment_id"] == "att_allowed"


def test_inspection_rejects_non_allowlisted_attachment(monkeypatch):
    tool = InspectAttachmentTool()
    tool.set_request_context(["att_allowed"], [])
    monkeypatch.setattr(tool, "_request", lambda *_args, **_kwargs: {"content": "leak"})

    assert tool.execute(attachment_id="att_other", question="read") == {
        "error": "attachment_forbidden",
        "items": [],
    }


def test_inspection_schema_documents_service_constraints():
    properties = InspectAttachmentTool().parameters["properties"]

    assert properties["attachment_id"]["minLength"] == 1
    assert properties["question"]["minLength"] == 1
    assert properties["question"]["maxLength"] == 4000
    assert properties["page"]["minimum"] == 1
    assert properties["page"]["maximum"] == 200
    assert properties["bbox"]["minItems"] == 4
    assert properties["bbox"]["maxItems"] == 4
    assert properties["bbox"]["items"]["minimum"] == 0
    assert properties["bbox"]["items"]["maximum"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"question": ""},
        {"question": "x" * 4001},
        {"question": 123},
        {"page": 0},
        {"page": 201},
        {"page": True},
        {"page": 1.5},
        {"bbox": []},
        {"bbox": [0, 0, 1]},
        {"bbox": [0, 0, 1, 1, 0]},
        {"bbox": [False, 0, 1, 1]},
        {"bbox": [0, "0", 1, 1]},
        {"bbox": [-0.1, 0, 1, 1]},
        {"bbox": [0, 0, 1.1, 1]},
        {"bbox": [0.5, 0, 0.4, 1]},
        {"bbox": [0, 0.5, 1, 0.4]},
        {"bbox": [0, 0, float("nan"), 1]},
    ],
)
def test_inspection_rejects_invalid_arguments_before_request(monkeypatch, overrides):
    tool = InspectAttachmentTool()
    tool.set_request_context(["att_allowed"], [])
    requests = []
    monkeypatch.setattr(
        tool,
        "_request",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )
    arguments = {
        "attachment_id": "att_allowed",
        "question": "Read the page.",
        "page": 2,
        "bbox": [0.1, 0.2, 0.8, 0.9],
    }
    arguments.update(overrides)

    result = tool.execute(**arguments)

    assert result == {"error": "invalid_attachment_query", "items": []}
    assert requests == []


@pytest.mark.parametrize("attachment_id", [None, 123, True, [], "", "   "])
def test_inspection_rejects_malformed_attachment_id_before_authorization_request(
    monkeypatch, attachment_id
):
    tool = InspectAttachmentTool()
    tool.set_request_context(["att_allowed"], [])
    requests = []
    monkeypatch.setattr(
        tool, "_request", lambda *args, **kwargs: requests.append((args, kwargs))
    )

    result = tool.execute(attachment_id=attachment_id, question="Read the page.")

    assert result == {"error": "invalid_attachment_query", "items": []}
    assert requests == []


def test_inspection_forwards_valid_page_and_bbox_unchanged(monkeypatch):
    tool = InspectAttachmentTool()
    tool.set_request_context(["att_allowed"], [])
    captured = {}

    def fake_request(path, payload, *, timeout_seconds):
        captured["path"] = path
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return {"content": "Recognized text."}

    monkeypatch.setattr(tool, "_request", fake_request)

    result = tool.execute(
        attachment_id="att_allowed",
        question="Read the highlighted text.",
        page=2,
        bbox=[0.1, 0.2, 0.8, 0.9],
    )

    assert result == {"items": [{"content": "Recognized text."}]}
    assert captured["path"] == "/v1/attachments/att_allowed/inspect"
    assert captured["payload"] == {
        "question": "Read the highlighted text.",
        "page": 2,
        "bbox": [0.1, 0.2, 0.8, 0.9],
    }
