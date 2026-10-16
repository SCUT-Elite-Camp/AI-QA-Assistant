from tests.grounding_helpers import grounded_model
"""Real Chat dispatcher, tools and source guard with controlled model/native IO."""

import pytest

from agent.agent import Agent
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.service.permission_service import PermissionResolutionError
from toolset.tool_layer import BaseTool
from toolset.tool_layer.evidence_metadata import source_metadata
from tests.integration.test_chat_evidence_security import fixture  # noqa: F401


class SourceTool(BaseTool):
    name = "search_documents"
    description = "Controlled enterprise source"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, documents):
        self.documents, self.calls = documents, []

    def execute(self, **arguments):
        pytest.fail("Search must use the structured contract")

    def search_direct(self, **arguments):
        self.calls.append(arguments)
        assert arguments["filters"]["doc_ids"] == ["doc1"]
        document = self.documents["doc1"]
        return [{"doc_id": "doc1", "chunk_id": "doc1_chunk_0", "chunk_index": 0,
                 "title": document["title"], "chunk_text": document["content"], "score": 1.0,
                 **source_metadata(document)}]

    def search(self, **arguments):
        pytest.fail("Fast must use direct retrieval without scope inference")


class CountingModel:
    def __init__(self, answer="Grounded answer [1]", after_call=None):
        self.calls, self.answer, self.after_call = [], answer, after_call

    @grounded_model
    def chat(self, messages, tools=None):
        assert tools is None
        self.calls.append(messages)
        if self.after_call:
            self.after_call()
        return {"content": self.answer}

    def stream_chat(self, messages, tools=None, **kwargs):
        yield {"content": self.chat(messages, tools, **kwargs)["content"]}


@pytest.mark.parametrize("stream", [False, True])
def test_fast_enters_same_pipeline_once_with_real_source_guard(fixture, monkeypatch, stream):
    guard, _, documents, *_ = fixture
    model, tool = CountingModel(), SourceTool(documents)
    agent = Agent(llm=model, tools=[tool], permission_service=guard.permissions)
    monkeypatch.setattr(agent.runner, "run", lambda *args, **kwargs: pytest.fail("Entered Thinking"))
    monkeypatch.setattr(agent.query_understanding, "analyze", lambda *args, **kwargs: pytest.fail("Rewrote question"))
    monkeypatch.setattr(agent.title_llm, "chat", lambda *args, **kwargs: pytest.fail("Extra title call"))
    request = ChatRequest(query="Compare the complete end-to-end flow", user_id="alice", weight_mode="fast", is_first_message=True)
    if stream:
        events = list(agent.stream_chat(request))
        done = events[-1][1]
        assert done["status"] == "success"
        assert done["evidence_provenance"]["complete"]
        assert [payload["content"] for name, payload in events if name == "token"] == ["Grounded answer [1]"]
    else:
        response = agent.chat(request)
        assert response.status == "success" and response.evidence_provenance.complete
        assert response.diagnostics is None or isinstance(response.diagnostics, dict)
    assert len(model.calls) == len(tool.calls) == 1
    assert tool.calls[0]["query"] == request.query


def test_fast_invalid_citation_never_releases_a_streamed_draft(fixture):
    guard, _, documents, *_ = fixture
    model = CountingModel("Unsupported source [99]")
    agent = Agent(llm=model, tools=[SourceTool(documents)], permission_service=guard.permissions)
    events = list(agent.stream_chat(ChatRequest(query="Question", user_id="alice", weight_mode="fast")))
    assert events[-1][1]["status"] == "quality_validation_failed"
    assert not any(name == "token" for name, _ in events)
    assert len(model.calls) == 1


@pytest.mark.parametrize("mode", ["thinking", "auto"])
@pytest.mark.parametrize("stream", [False, True])
def test_thinking_scope_clarification_uses_same_flow_without_model(fixture, mode, stream):
    guard, *_ = fixture
    model = CountingModel()
    agent = Agent(llm=model, tools=[], permission_service=guard.permissions)
    request = ChatRequest(query="Explain the latest architecture", user_id="alice", weight_mode=mode)
    if stream:
        events = list(agent.stream_chat(request))
        assert events[-1][1]["status"] == "clarification_required"
        assert any(name == "token" and "which architecture" in payload["content"] for name, payload in events)
    else:
        response = agent.chat(request)
        assert response.status == "clarification_required" and "which architecture" in response.message
    assert not model.calls


def test_fast_rechecks_source_version_after_its_only_generation(fixture):
    guard, _, documents, *_ = fixture
    def change_source():
        documents["doc1"]["content"] = "Changed source body"
    model = CountingModel(after_call=change_source)
    agent = Agent(llm=model, tools=[SourceTool(documents)], permission_service=guard.permissions)
    with pytest.raises(PermissionResolutionError, match="document_version_changed"):
        agent.chat(ChatRequest(query="Question", user_id="alice", weight_mode="fast"))
    assert len(model.calls) == 1


@pytest.mark.parametrize("mode", ["thinking", "auto"])
def test_thinking_and_auto_never_enter_fast_even_for_a_simple_question(fixture, monkeypatch, mode):
    guard, *_ = fixture
    model = CountingModel("Hello")
    class Understanding:
        def analyze(self, query, *args, **kwargs):
            return QueryPlan(original_query=query, standalone_query=query, intent=QueryIntent.CASUAL_CHAT)
    agent = Agent(llm=model, tools=[], permission_service=guard.permissions, query_understanding=Understanding())
    monkeypatch.setattr(agent.fast_pipeline, "run", lambda *args, **kwargs: pytest.fail("Entered Fast"))
    response = agent.chat(ChatRequest(query="Hello", user_id="alice", weight_mode=mode, is_first_message=False))
    assert response.status == "success" and response.answer == "Hello"
    assert agent.last_orchestration.execution_profile.mode.value == "thinking"
    assert len(model.calls) == 1
