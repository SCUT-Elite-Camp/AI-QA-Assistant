from tests.grounding_helpers import grounded_model, control_response
import json
from typing import Any

import pytest

from agent.agent import Agent
from agent.config.settings import settings
from agent.memory import MemoryCoordinator
from agent.schemas.chat import ChatRequest, InternalChatRequest
from agent.schemas.common import StatusCode
from agent.schemas.query_plan import QueryIntent, QueryPlan
from toolset.tool_layer import BaseTool


class InspectingLLM:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.messages_seen: list[list[dict[str, Any]]] = []
        self.control_messages = []

    def generate(self, prompt: str) -> str:
        return prompt

    @grounded_model
    def chat(self, messages: list[dict], tools=None, **kwargs) -> dict:
        system_prompt = messages[0].get("content", "") if messages else ""
        if 'Thinking question-answering Agent' in system_prompt:
            self.control_messages.append(list(messages))
            if self.answers and self.answers[0].startswith('{'):
                return control_response(**json.loads(self.answers.pop(0)))
            if not any('[TOOL_OBSERVATIONS]' in str(msg.get('content','')) for msg in messages):
                return {"tool_calls": [{"id":"search", "function":{"name":"search_documents", "arguments":json.dumps({"query":"delivery requirements"})}}]}
            return control_response("answer")
        self.messages_seen.append(list(messages))
        return {"role": "assistant", "content": self.answers.pop(0)}


class MemorySearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Return one deterministic test document."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "mode": {"type": "string"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.search(**kwargs)

    def search_direct(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.search(**kwargs)

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        query = kwargs["query"]
        return [{
            "doc_id": "doc-memory",
            "chunk_id": "doc-memory::chunk-0",
            "chunk_index": 0,
            "chunk_text": f"Evidence for {query}",
            "title": "Memory test document",
            "source_url": "https://example.test/memory",
            "score": 0.95,
        }]


def persistent_memory_context() -> dict:
    return {
        "actor": {"user_id": "user-a", "authenticated": True},
        "chat_id": "persistent-chat",
        "revision": 1,
        "current_message_id": "message-3",
        "current_sequence": 3,
        "snapshot": {
            "id": "snapshot-1",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 1,
            "summary": "Earlier discussion summary.",
        },

        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 1,
                "role": "assistant",
                "content": "Earlier assistant answer.",
            }
        ],
    }


def test_persistent_context_reaches_thinking_loop_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    llm = InspectingLLM(["Persistent answer [1]"])
    agent = Agent(llm=llm, tools=[MemorySearchTool()])
    request = InternalChatRequest(
        query="Current persistent question",
        session_id="persistent-chat",
        is_first_message=False,
        weight_mode="thinking",
        memory_context=persistent_memory_context(

        ),
    )

    response = agent.chat(request)

    assert response.status == StatusCode.SUCCESS
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.context_artifact is not None
    runner_messages = llm.control_messages[0]
    assert [message["role"] for message in runner_messages] == [
        "system",
        "system",
        "assistant",
        "user",
        "user",
    ]
    assert "Memory Context follows" in runner_messages[1]["content"]
    assert "Earlier discussion summary." in runner_messages[1]["content"]
    assert runner_messages[2]["content"] == "Earlier assistant answer."
    assert runner_messages[-2]["content"] == "Current persistent question"
    assert sum(
        message["content"] == "Current persistent question"
        for message in runner_messages
    ) == 1
    assert agent.last_orchestration.execution_profile is not None
    assert agent.last_orchestration.execution_profile.mode.value == "thinking"


def test_persistent_context_reaches_fast_pipeline_once(monkeypatch) -> None:
    from unittest.mock import Mock

    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    coordinator = MemoryCoordinator()
    coordinator.prepare = Mock(wraps=coordinator.prepare)  # type: ignore[method-assign]
    llm = InspectingLLM(["Fast persistent answer [1]"])
    agent = Agent(
        llm=llm,
        tools=[MemorySearchTool()],
        memory_coordinator=coordinator,
    )
    request = InternalChatRequest(
        query="Current persistent question",
        session_id="persistent-chat",
        is_first_message=False,
        weight_mode="fast",
        memory_context=persistent_memory_context(),
    )

    response = agent.chat(request)

    assert response.status == StatusCode.SUCCESS
    assert coordinator.prepare.call_count == 1
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.execution_profile is not None
    assert agent.last_orchestration.execution_profile.mode.value == "fast"
    assert agent.last_orchestration.context_artifact is not None
    fast_messages = llm.messages_seen[-1]
    assert "Memory Context follows" in fast_messages[1]["content"]
    assert fast_messages[2]["content"] == "Earlier assistant answer."
    assert "Original question:\nCurrent persistent question" in fast_messages[-1]["content"]


def test_repeated_requests_do_not_share_implicit_session_history() -> None:
    llm = InspectingLLM(["First answer", "Second answer", "New chat answer"])
    agent = Agent(llm=llm, tools=[])

    first = agent.chat(ChatRequest(knowledge_base_retrieval_enabled=False, query="First question", session_id="session-a"))
    second = agent.chat(ChatRequest(knowledge_base_retrieval_enabled=False, query="Continue the explanation", session_id="session-a"))
    third = agent.chat(ChatRequest(knowledge_base_retrieval_enabled=False, query="Another question", session_id="session-b"))

    assert first.status == second.status == third.status == StatusCode.SUCCESS
    second_messages = llm.messages_seen[1]
    assert "First question" not in {message.get("content") for message in second_messages}
    assert "First answer" not in {message.get("content") for message in second_messages}
    assert "First question" not in {
        message.get("content") for message in llm.messages_seen[2]
    }


def test_missing_memory_context_is_stateless_even_with_session_id() -> None:
    llm = InspectingLLM(["First answer", "Second answer"])
    agent = Agent(llm=llm, tools=[])

    agent.chat(ChatRequest(knowledge_base_retrieval_enabled=False, query="Stateless question"))
    agent.chat(ChatRequest(knowledge_base_retrieval_enabled=False, query="Second stateless question"))

    assert all(
        message.get("content") != "Stateless question"
        for message in llm.messages_seen[1]
    )


def test_clarification_question_is_not_saved_to_agent_memory() -> None:
    llm = InspectingLLM(['{"action":"clarify","question":"Which document do you mean?"}'])
    agent = Agent(llm=llm, tools=[])
    query = "When was it updated?"
    plan = QueryPlan(
        original_query=query,
        standalone_query=query,
        needs_clarification=True,
        clarification_question="Legacy hint is ignored.",
        ambiguity_reason="Missing referent",
    )

    response = agent.chat(
        ChatRequest(query=query, session_id="session-clarify", weight_mode="thinking"),
        query_plan=plan,
    )

    assert response.status == StatusCode.CLARIFICATION_REQUIRED
    assert response.answer == ""
    assert response.message == "Which document do you mean?"
    assert len(llm.control_messages) == 1
    assert llm.messages_seen == []


def test_query_plan_filters_merge_through_chat_orchestration() -> None:
    query = "Summarize the document"
    plan = QueryPlan(
        original_query=query,
        standalone_query="Summarize doc-1",
        intent=QueryIntent.CASUAL_CHAT,
        filters={"space_key": "RAG", "doc_id": "doc-1"},
    )
    request = ChatRequest(
        query=query,
        filters={"doc_type": "md"},
        weight_mode="thinking",
        is_first_message=False,
    )
    agent = Agent(llm=InspectingLLM(["Summary [1]."]), tools=[MemorySearchTool()])

    response = agent.chat(request, query_plan=plan)

    assert response.status == StatusCode.SUCCESS
    assert agent.last_orchestration is not None
    resolved = agent.last_orchestration.query_plan
    assert resolved.standalone_query == query
    assert resolved.filters == {
        "space_key": "RAG",
        "doc_id": "doc-1",
        "doc_type": "md",
    }


def test_conflicting_hard_filters_are_rejected() -> None:
    query = "Summarize the document"
    plan = QueryPlan(
        original_query=query,
        standalone_query=query,
        filters={"space_key": "RAG"},
    )

    response = Agent(llm=InspectingLLM([]), tools=[]).chat(
        ChatRequest(query=query, filters={"space_key": "PRIVATE"}),
        query_plan=plan,
    )

    assert response.status == StatusCode.INVALID_QUERY
    assert response.message and not response.answer
