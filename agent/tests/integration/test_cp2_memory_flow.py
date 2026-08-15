import json
from typing import Any

import pytest

from agent.agent import Agent
from agent.config.settings import settings
from agent.memory import InMemoryConversationMemory
from agent.schemas.chat import ChatRequest, InternalChatRequest
from agent.schemas.common import StatusCode
from agent.schemas.query_plan import QueryPlan


@pytest.fixture(autouse=True)
def isolate_query_understanding_mode_from_local_env(monkeypatch) -> None:
    """Keep scripted integration tests independent of a developer's .env."""

    monkeypatch.setattr(settings, "UNIFIED_QUERY_UNDERSTANDING_ENABLED", False)
    monkeypatch.setattr(settings, "CASCADED_QUERY_UNDERSTANDING_ENABLED", False)
    monkeypatch.setattr(settings, "HYBRID_INTENT_ROUTER_ENABLED", False)


class InspectingLLM:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.messages_seen: list[list[dict[str, Any]]] = []

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        system_prompt = messages[0].get("content", "") if messages else ""
        if "classify user requests" in system_prompt:
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "intent": "knowledge_qa",
                        "confidence": 1.0,
                        "is_follow_up": False,
                        "is_clarification_reply": False,
                        "reason": "test",
                    }
                ),
            }
        if "澄清判断器" in system_prompt:
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "needs_clarification": False,
                        "question": "",
                        "reason": "test",
                    }
                ),
            }
        if "查询重写器" in system_prompt:
            return {
                "role": "assistant",
                "content": json.dumps(
                    {"rewritten_query": "测试独立查询", "reason": "test"}
                ),
            }
        if "Plan retrieval" in system_prompt:
            return {
                "role": "assistant",
                "content": json.dumps(
                    {"sub_queries": [], "filters": {}, "reason": "test"}
                ),
            }
        self.messages_seen.append(list(messages))
        return {"role": "assistant", "content": self.answers.pop(0)}


class NoModelCallLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        self.calls += 1
        raise AssertionError("explicit memory recall must not call an LLM")


def persistent_memory_context(*, facts: list[dict] | None = None) -> dict:
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
        "facts": facts or [],
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


def test_persistent_context_reaches_runner_once_and_skips_legacy_double_write(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    memory = InMemoryConversationMemory()
    llm = InspectingLLM(["Persistent answer [1]"])
    agent = Agent(llm=llm, tools=[], memory=memory)
    request = InternalChatRequest(
        query="Current persistent question",
        session_id="persistent-chat",
        is_first_message=False,
        memory_context=persistent_memory_context(
            facts=[
                {
                    "id": "fact-1",
                    "category": "PREFERENCE",
                    "value": "Use concise Chinese.",
                    "expires_at": None,
                }
            ]
        ),
    )

    assert agent._is_persistent_memory_request(request) is True
    response = agent.chat(request)

    assert response.status == StatusCode.SUCCESS
    assert agent._is_persistent_memory_request(request) is True
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.context_artifact is not None
    runner_messages = llm.messages_seen[-1]
    assert [message["role"] for message in runner_messages] == [
        "system",
        "system",
        "assistant",
        "user",
    ]
    assert "Memory Context follows" in runner_messages[1]["content"]
    assert "Use concise Chinese." in runner_messages[1]["content"]
    assert runner_messages[2]["content"] == "Earlier assistant answer."
    assert runner_messages[-1]["content"] == "Current persistent question"
    assert sum(
        message["content"] == "Current persistent question"
        for message in runner_messages
    ) == 1
    assert memory.get_messages("persistent-chat") == []


def test_explicit_persistent_fact_recall_bypasses_models_and_agent_audit_storage(
    monkeypatch,
) -> None:
    from unittest.mock import MagicMock

    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    memory = InMemoryConversationMemory()
    llm = NoModelCallLLM()
    agent = Agent(llm=llm, tools=[], memory=memory)
    agent.audit_service.record = MagicMock()
    request = InternalChatRequest(
        query="我之前确认的目标是什么？",
        session_id="persistent-chat",
        is_first_message=False,
        memory_context=persistent_memory_context(
            facts=[
                {
                    "id": "fact-1",
                    "category": "GOAL",
                    "value": "完成答辩准备。",
                    "expires_at": None,
                }
            ]
        ),
    )

    response = agent.chat(request)

    assert response.status == StatusCode.SUCCESS
    assert response.answer == "你此前确认的目标：\n- 完成答辩准备。"
    assert response.citations == []
    assert llm.calls == 0
    assert agent.last_run_result is None
    assert memory.get_messages("persistent-chat") == []
    agent.audit_service.record.assert_not_called()


def test_same_session_history_is_injected_but_other_sessions_are_isolated() -> None:
    memory = InMemoryConversationMemory(max_messages=10)
    llm = InspectingLLM(["第一次回答", "第二次回答", "新会话回答"])
    agent = Agent(llm=llm, tools=[], memory=memory)

    first = agent.chat(ChatRequest(query="第一个问题", session_id="session-a"))
    second = agent.chat(ChatRequest(query="接着说", session_id="session-a"))
    third = agent.chat(ChatRequest(query="另一个问题", session_id="session-b"))

    assert first.status == second.status == third.status == StatusCode.SUCCESS
    second_messages = llm.messages_seen[1]
    assert {"role": "user", "content": "第一个问题"} in second_messages
    assert {"role": "assistant", "content": "第一次回答"} in second_messages
    assert "第一个问题" not in {
        message.get("content") for message in llm.messages_seen[2]
    }


def test_missing_session_id_does_not_read_or_write_memory() -> None:
    memory = InMemoryConversationMemory()
    llm = InspectingLLM(["第一次回答", "第二次回答"])
    agent = Agent(llm=llm, tools=[], memory=memory)

    agent.chat(ChatRequest(query="无会话问题"))
    agent.chat(ChatRequest(query="第二个无会话问题"))

    assert all(
        message.get("content") != "无会话问题"
        for message in llm.messages_seen[1]
    )
    assert memory.get_messages("unused-session") == []


def test_clarification_question_is_saved_without_calling_llm_or_tools() -> None:
    memory = InMemoryConversationMemory()
    llm = InspectingLLM([])
    agent = Agent(llm=llm, tools=[], memory=memory)
    query = "它什么时候更新？"
    plan = QueryPlan(
        original_query=query,
        standalone_query=query,
        needs_clarification=True,
        clarification_question="你指的是哪个文档？",
        ambiguity_reason="缺少指代对象",
    )

    response = agent.chat(
        ChatRequest(query=query, session_id="session-clarify"),
        query_plan=plan,
    )

    assert response.status == StatusCode.CLARIFICATION_REQUIRED
    assert response.answer == ""
    assert response.message == "你指的是哪个文档？"
    assert llm.messages_seen == []
    assert memory.get_messages("session-clarify") == [
        {"role": "user", "content": query},
        {"role": "assistant", "content": "你指的是哪个文档？"},
    ]


def test_query_plan_filters_merge_without_losing_hard_constraints() -> None:
    query = "总结文档"
    plan = QueryPlan(
        original_query=query,
        standalone_query="总结 doc-1",
        filters={"space_key": "RAG", "doc_id": "doc-1"},
    )
    request = ChatRequest(
        query=query,
        filters={"doc_type": "md"},
    )

    resolved = Agent._resolve_query_plan(request, plan)

    assert resolved.standalone_query == "总结 doc-1"
    assert resolved.filters == {
        "space_key": "RAG",
        "doc_id": "doc-1",
        "doc_type": "md",
    }


def test_conflicting_hard_filters_are_rejected() -> None:
    query = "总结文档"
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
    assert response.message == "查询计划与当前请求不一致。"
