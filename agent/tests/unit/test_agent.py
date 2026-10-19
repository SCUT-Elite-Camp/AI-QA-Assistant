from tests.grounding_helpers import grounded_content
import json
from contextvars import Context
from unittest.mock import MagicMock

import pytest

from agent.agent import Agent
from agent.errors.exceptions import LLMError
from agent.llm.llm_client import LLMClient
from agent.schemas.chat import ChatRequest, InternalChatRequest
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult
from toolset.tool_layer.search_tool import SearchTool


def test_normal_query_returns_success() -> None:
    # LLMClient.chat is mocked by conftest fixture autouse
    response = Agent().chat(ChatRequest(query="What features are required for project Q1?"))

    assert response.status == StatusCode.SUCCESS
    assert response.answer
    assert len(response.citations) > 0
    assert response.trace_id.startswith("trace-")


def test_empty_query_returns_invalid_query() -> None:
    response = Agent().chat(ChatRequest(query="   "))

    assert response.status == StatusCode.INVALID_QUERY
    assert response.answer == ""
    assert response.message and not response.answer
    assert response.citations == []


def test_compatibility_diagnostics_are_request_context_local() -> None:
    agent = Agent()
    other_request = Context()

    other_request.run(
        lambda: (
            setattr(agent, "last_run_result", object()),
            setattr(agent, "last_orchestration", object()),
            setattr(agent, "last_citation_check", object()),
        )
    )

    assert agent.last_run_result is None
    assert agent.last_orchestration is None
    assert agent.last_citation_check is None


def test_empty_retrieval_returns_no_relevant_context(monkeypatch) -> None:
    # Mock SearchTool.search to return empty list
    monkeypatch.setattr(SearchTool, "search", lambda *args, **kwargs: [])

    response = Agent().chat(ChatRequest(query="A question outside the knowledge base"))

    assert response.status == StatusCode.NO_RELEVANT_CONTEXT
    assert response.answer == ""
    assert response.citations == []


def test_retrieval_error_returns_retrieval_error(monkeypatch) -> None:
    # Mock SearchTool.search to raise an error
    def mock_raise(*args, **kwargs):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(SearchTool, "search", mock_raise)

    response = Agent().chat(ChatRequest(query="Trigger a retrieval failure"))

    assert response.status in (StatusCode.LLM_ERROR, StatusCode.RETRIEVAL_ERROR)
    assert response.answer == ""


def test_llm_error_returns_llm_error(monkeypatch) -> None:
    # Mock LLMClient.chat to raise an exception
    def mock_chat_raise(*args, **kwargs):
        raise LLMError("LLM disconnect")
    monkeypatch.setattr(LLMClient, "chat", mock_chat_raise)

    response = Agent().chat(ChatRequest(query="Trigger a model failure"))

    assert response.status == StatusCode.LLM_ERROR
    assert response.message == "The Fast model request failed."


def test_chat_service_passes_week2_retrieval_parameters(monkeypatch) -> None:
    monkeypatch.setattr(LLMClient, "chat", lambda *args, **kwargs: {"content": json.dumps({
        "claims": [{"text": "Test source context",
            "supports": [{"citation_id": 1, "quote": "Test source context"}]}],
    }, ensure_ascii=False)})
    called_params = {}

    def mock_search(self, query, top_k=5, mode="hybrid", filters=None, min_score=0.0, trace_id=None):
        called_params["query"] = query
        called_params["top_k"] = top_k
        called_params["mode"] = mode
        called_params["filters"] = filters
        return [{
            "doc_id": "doc-1",
            "chunk_id": "doc-1::chunk_0",
            "chunk_index": 0,
            "chunk_text": "Test source context",
            "title": "Test document",
            "source_url": "",
            "score": 0.9,
        }]

    monkeypatch.setattr(SearchTool, "search", mock_search)

    response = Agent().chat(
        ChatRequest(
            query="  What is planned for week two? ",
            top_k=3,
            filters={"doc_type": "md"},
            retrieval_mode="bm25",
        )
    )

    assert response.status == StatusCode.SUCCESS
    assert called_params["query"] == "  What is planned for week two? "


def test_low_score_retrieval_returns_no_relevant_context(monkeypatch) -> None:
    monkeypatch.setattr("agent.config.settings.settings.MIN_RETRIEVAL_SCORE", 0.8)

    # Mock search to return low-score chunk
    def mock_search(*args, **kwargs):
        return [{
            "doc_id": "doc-low",
            "chunk_id": "doc-low::chunk_0",
            "chunk_index": 0,
            "chunk_text": "Low-relevance context",
            "title": "Low-relevance document",
            "source_url": "",
            "score": 0.2,
        }]
    monkeypatch.setattr(SearchTool, "search", mock_search)

    response = Agent().chat(ChatRequest(query="A question outside the knowledge base"))

    assert response.status == StatusCode.NO_RELEVANT_CONTEXT
    assert response.answer == ""
    assert response.citations == []


def test_empty_llm_answer_returns_llm_error(monkeypatch) -> None:
    # Mock LLMClient.chat to return empty content
    monkeypatch.setattr(LLMClient, "chat", lambda *args, **kwargs: {"role": "assistant", "content": "   "})

    response = Agent().chat(ChatRequest(query="Trigger an empty model answer"))

    assert response.status == StatusCode.LLM_ERROR
    assert response.answer == ""
    assert response.citations == []




def test_agent_configures_non_thinking_fast_answer_model(monkeypatch) -> None:
    monkeypatch.setattr("agent.agent.settings.LLM_MODEL", "main-answer-model")
    monkeypatch.setattr("agent.agent.settings.ANSWER_FAST_MODEL", "qwen-flash")
    monkeypatch.setattr("agent.agent.settings.ANSWER_FAST_MODEL_THINKING", False)

    agent = Agent()

    assert agent.runtime_llm.llm.model == "main-answer-model"
    assert agent.fast_answer_llm.llm.model == "qwen-flash"
    assert agent.fast_answer_llm.llm.enable_thinking is False
    assert agent.runner.llm is agent.runtime_llm
    assert not hasattr(agent, "query_understanding")
    assert not hasattr(agent, "title_llm")
    assert agent.llm.attempts_per_model == 1






def test_explicit_internal_fact_command_bypasses_llm_and_rag(monkeypatch) -> None:
    monkeypatch.setattr("agent.config.settings.settings.PERSISTENT_MEMORY_ENABLED", True)
    monkeypatch.setattr("agent.config.settings.settings.SESSION_FACT_ENABLED", True)

    agent = Agent()
    monkeypatch.setattr(
        agent.orchestrator,
        "run",
        lambda *args, **kwargs: pytest.fail("explicit Fact commands must not invoke orchestration"),
    )

    response, decision = agent.chat_with_memory(
        InternalChatRequest(
            query="Remember goal: Complete the local Memory demo",
            session_id="fact-command-session",
            memory_context={
                "actor": {"user_id": "user-1", "authenticated": True},
                "chat_id": "chat-1",
                "revision": 1,
                "current_message_id": "message-1",
                "current_sequence": 1,
                "snapshot": None,
                "facts": [],
                "tail": [],
            },
        )
    )

    assert response.status == StatusCode.SUCCESS
    assert response.citations == []
    assert response.answer == "A session memory suggestion is ready. Please confirm it in the interface."
    assert [(proposal.category, proposal.value, proposal.source_message_id, proposal.expires_at) for proposal in decision.fact_proposals] == [
        ("GOAL", "Complete the local Memory demo", "message-1", None),
    ]
