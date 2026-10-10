import json

from typing import Any

from agent.agent import Agent

from agent.memory import InMemoryConversationMemory

from agent.policy import ChatRoute

from agent.query import QueryUnderstanding

from agent.config.settings import settings

from agent.schemas.chat import (
    ChatRequest,
    InternalActor,
    InternalChatRequest,
    MemoryContextInput,
    MemoryFactInput,
    MemoryMessage,
    MemorySnapshotInput,
)

from agent.schemas.query_plan import QueryIntent, QueryPlan

from toolset.tool_layer import BaseTool


import json
import threading
import time
from typing import Any

from agent.agent import Agent
from agent.memory import InMemoryConversationMemory
from agent.query import QueryUnderstanding
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryIntent, QueryPlan
from toolset.tool_layer import BaseTool


class PipelineLLM:
    """Script the four Query Understanding calls and the Runner calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        system = messages[0].get("content", "") if messages else ""
        self.calls.append({"messages": list(messages), "tools": tools})

        if "classify user requests" in system:
            return self._json(
                {
                    "intent": "knowledge_qa",
                    "confidence": 0.99,
                    "is_follow_up": False,
                    "is_clarification_reply": False,
                    "reason": "knowledge question",
                }
            )
        if "澄清判断器" in system:
            return self._json(
                {"needs_clarification": False, "question": "", "reason": "clear"}
            )
        if "Rewrite the current question" in system:
            return self._json(
                {
                    "rewritten_query": "rewritten standalone query",
                    "reason": "resolved references",
                }
            )
        if "Plan retrieval" in system:
            return self._json(
                {"sub_queries": [], "filters": {}, "reason": "single query"}
            )

        if tools and not any(message.get("role") == "tool" for message in messages):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": "model query"}),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "最终答案 [1]"}

    @staticmethod
    def _json(payload: dict[str, Any]) -> dict[str, Any]:
        return {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}


class MultiSearchPipelineLLM(PipelineLLM):
    """Simulate a provider returning redundant searches in one response."""

    def chat(self, messages: list[dict], tools=None) -> dict:
        if tools and not any(message.get("role") == "tool" for message in messages):
            call = {
                "type": "function",
                "function": {
                    "name": "search_documents",
                    "arguments": json.dumps({"query": "model query"}),
                },
            }
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-search-1", **call},
                    {"id": "call-search-2", **call},
                ],
            }
        return super().chat(messages, tools=tools)


class PostEvidenceToolCallLLM(PipelineLLM):
    """Simulate a provider emitting a stale tool call during answer generation."""

    def chat(self, messages: list[dict], tools=None) -> dict:
        has_evidence = any(message.get("role") == "tool" for message in messages)
        has_final_only_instruction = any(
            "Retrieval is complete" in str(message.get("content") or "")
            for message in messages
        )
        if has_evidence and not has_final_only_instruction:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "stale-search",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": "stale query"}),
                        },
                    }
                ],
            }
        return super().chat(messages, tools=tools)


class RecordingSearchTool(BaseTool):
    def __init__(
        self,
        *,
        comparison: bool = False,
        delay_seconds: float = 0.0,
        fail_first_for: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.comparison = comparison
        self.delay_seconds = delay_seconds
        self.fail_first_for = fail_first_for
        self._failed_queries: set[str] = set()
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Search test documents."

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

    def execute(self, **kwargs: Any) -> Any:
        return self.search(**kwargs)

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        query = kwargs["query"]
        with self._lock:
            self.calls.append(dict(kwargs))
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if query == self.fail_first_for and query not in self._failed_queries:
                self._failed_queries.add(query)
                raise RuntimeError(f"temporary failure for {query}")
        finally:
            with self._lock:
                self.active_calls -= 1
        return [
            {
                "doc_id": f"doc-{query}",
                "chunk_id": f"doc-{query}::chunk-0",
                "chunk_index": 0,
                "chunk_text": f"Evidence for {query}",
                "title": f"Document {query}",
                "source_url": f"https://example.test/{query}",
                "score": 0.95,
            }
        ]


class FixedQueryUnderstanding:
    def __init__(self, plan: QueryPlan) -> None:
        self.plan = plan
        self.calls: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []

    def analyze(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        *,
        filters: dict[str, Any] | None = None,
    ) -> QueryPlan:
        self.calls.append((query, list(history or []), dict(filters or {})))
        merged = dict(self.plan.filters)
        merged.update(filters or {})
        return self.plan.model_copy(update={"original_query": query, "filters": merged})


def test_default_chat_uses_query_plan_policy_executor_gate_and_citation_check() -> None:
    llm = PipelineLLM()
    memory = InMemoryConversationMemory()
    search = RecordingSearchTool()
    agent = Agent(llm=llm, tools=[search], memory=memory)

    response = agent.chat(
        ChatRequest(
            query="这个功能怎么用？",
            session_id="orchestration-session",
            retrieval_mode="bm25",
            top_k=3,
        )
    )

    assert response.status == "success"
    assert response.citations[0].doc_id == "doc-rewritten standalone query"
    assert search.calls[0]["query"] == "rewritten standalone query"
    assert search.calls[0]["mode"] == "bm25"
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.query_plan.standalone_query == (
        "rewritten standalone query"
    )
    assert agent.last_orchestration.policy.candidate_tools == ("search_documents",)
    assert agent.last_citation_check is not None
    assert agent.last_citation_check.valid is True
    assert memory.get_messages("orchestration-session")[-1]["role"] == "assistant"


def test_comparison_parallel_retrieval_isolates_failure_and_corrects_missing_side() -> None:
    plan = QueryPlan(
        original_query="compare A and B",
        standalone_query="A and B",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B"],
    )
    search = RecordingSearchTool(
        comparison=True,
        delay_seconds=0.05,
        fail_first_for="B",
    )
    agent = Agent(
        llm=PipelineLLM(),
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=FixedQueryUnderstanding(plan),  # type: ignore[arg-type]
    )

    response = agent.chat(
        ChatRequest(query="compare A and B", session_id="partial-failure", top_k=3)
    )

    assert response.status == "success"
    assert agent.last_orchestration is not None
    result = agent.last_orchestration.run_result
    assert result.retrieval_attempts == 2
    assert result.missing_evidence_targets == []
    assert sorted(call["query"] for call in search.calls) == ["A", "B", "B"]
    assert search.max_active_calls == 2


def test_comparison_flow_runs_corrective_retrieval_before_final_answer() -> None:
    plan = QueryPlan(
        original_query="比较 A 和 B",
        standalone_query="A 和 B",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B"],
    )
    understanding = FixedQueryUnderstanding(plan)
    llm = PipelineLLM()
    search = RecordingSearchTool(comparison=True, delay_seconds=0.05)
    agent = Agent(
        llm=llm,
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=understanding,  # type: ignore[arg-type]
    )

    response = agent.chat(
        ChatRequest(query="比较 A 和 B", session_id="comparison-session", top_k=3)
    )

    assert response.status == "success"
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.run_result.retrieval_attempts == 1
    assert sorted(call["query"] for call in search.calls) == ["A", "B"]
    assert search.max_active_calls == 2
    assert agent.last_citation_check is not None
    assert agent.last_citation_check.valid is True


def test_comparison_parallel_retrieval_supports_three_bounded_targets() -> None:
    plan = QueryPlan(
        original_query="summarize A, B, and C and compare them",
        standalone_query="A B C comparison",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B", "C"],
    )
    search = RecordingSearchTool(comparison=True, delay_seconds=0.05)
    agent = Agent(
        llm=PipelineLLM(),
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=FixedQueryUnderstanding(plan),  # type: ignore[arg-type]
    )

    response = agent.chat(
        ChatRequest(query=plan.original_query, session_id="three-targets", top_k=3)
    )

    assert response.status == "success"
    assert agent.last_orchestration is not None
    result = agent.last_orchestration.run_result
    assert result.retrieval_attempts == 1
    assert sorted(call["query"] for call in search.calls) == ["A", "B", "C"]
    assert search.max_active_calls == 3


def test_comparison_ignores_redundant_searches_after_batch_evidence_is_accepted() -> None:
    plan = QueryPlan(
        original_query="compare A and B",
        standalone_query="A and B",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B"],
    )
    search = RecordingSearchTool(comparison=True)
    agent = Agent(
        llm=MultiSearchPipelineLLM(),
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=FixedQueryUnderstanding(plan),  # type: ignore[arg-type]
    )

    response = agent.chat(
        ChatRequest(query=plan.original_query, session_id="redundant-searches")
    )

    assert response.status == "success"
    assert agent.last_orchestration is not None
    result = agent.last_orchestration.run_result
    assert result.stop_reason.value == "final_answer"
    assert len(result.tool_calls) == 1
    assert sorted(call["query"] for call in search.calls) == ["A", "B"]


def test_comparison_reprompts_instead_of_executing_post_evidence_tool_call() -> None:
    plan = QueryPlan(
        original_query="compare A and B",
        standalone_query="A and B",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B"],
    )
    search = RecordingSearchTool(comparison=True)
    agent = Agent(
        llm=PostEvidenceToolCallLLM(),
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=FixedQueryUnderstanding(plan),  # type: ignore[arg-type]
    )

    response = agent.chat(
        ChatRequest(query=plan.original_query, session_id="post-evidence-tool")
    )

    assert response.status == "success"
    assert agent.last_orchestration is not None
    result = agent.last_orchestration.run_result
    assert result.stop_reason.value == "final_answer"
    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert sorted(call["query"] for call in search.calls) == ["A", "B"]


def test_persistent_context_is_used_without_legacy_short_window_double_write(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    llm = PipelineLLM()
    memory = InMemoryConversationMemory()
    agent = Agent(llm=llm, tools=[RecordingSearchTool()], memory=memory)

    response, decision = agent.chat_with_memory(
        _persistent_request("What did we discuss?")
    )

    assert response.status == "success"
    assert decision.context_artifact is not None
    assert decision.fact_proposals == []
    assert decision.recall is None
    assert agent.last_orchestration is not None
    assert [message["role"] for message in agent.last_orchestration.history] == [
        "system",
        "assistant",
    ]
    runner_messages = next(call["messages"] for call in llm.calls if call["tools"])
    assert [message["role"] for message in runner_messages[:4]] == [
        "system",
        "system",
        "assistant",
        "user",
    ]
    assert runner_messages[-1]["content"] == "What did we discuss?"
    assert memory.get_messages("persistent-session") == []



def test_explicit_persistent_fact_recall_bypasses_model_and_legacy_short_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "SESSION_FACT_ENABLED", True)
    llm = PipelineLLM()
    memory = InMemoryConversationMemory()
    agent = Agent(llm=llm, tools=[RecordingSearchTool()], memory=memory)

    response, decision = agent.chat_with_memory(
        _persistent_request(
            "我记住了什么？",
            facts=[
                MemoryFactInput(
                    id="fact-1",
                    category="GOAL",
                    value="完成答辩准备。",
                    expires_at=None,
                )
            ],
        )
    )

    assert response.status == "success"
    assert response.answer == "已确认的记忆：\n- GOAL: 完成答辩准备。"
    assert response.citations == []
    assert decision.recall is not None and decision.recall.handled is True
    assert decision.fact_proposals == []
    assert llm.calls == []
    assert memory.get_messages("persistent-session") == []
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.chat_route.route == ChatRoute.L0_DIRECT
    assert agent.last_orchestration.chat_route.research_entry_allowed is False



def test_persistent_success_returns_one_explicit_fact_proposal_only_when_gated_on(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "SESSION_FACT_ENABLED", True)
    agent = Agent(
        llm=PipelineLLM(),
        tools=[RecordingSearchTool()],
        memory=InMemoryConversationMemory(),
    )

    response, decision = agent.chat_with_memory(
        _persistent_request("请记住偏好： 使用  中文\n回复 ")
    )

    assert response.status == "success"
    assert response.model_dump().keys() >= {
        "trace_id", "status", "answer", "message", "citations", "chat_title"
    }
    assert [proposal.model_dump() for proposal in decision.fact_proposals] == [
        {
            "category": "PREFERENCE",
            "value": "使用 中文 回复",
            "source_message_id": "message-3",
            "expires_at": None,
        }
    ]



def test_fact_proposal_policy_failure_is_non_blocking_and_does_not_create_a_candidate(
    monkeypatch,
) -> None:
    class RaisingFactProposalPolicy:
        def propose(self, *args, **kwargs):
            raise RuntimeError("candidate policy unavailable")

    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "SESSION_FACT_ENABLED", True)
    agent = Agent(
        llm=PipelineLLM(),
        tools=[RecordingSearchTool()],
        memory=InMemoryConversationMemory(),
        fact_proposal_policy=RaisingFactProposalPolicy(),  # type: ignore[arg-type]
    )

    response, decision = agent.chat_with_memory(
        _persistent_request("remember goal: finish the implementation")
    )

    assert response.status == "success"
    assert decision.fact_proposals == []


def _persistent_request(
    query: str,
    *,
    facts: list[MemoryFactInput] | None = None,
) -> InternalChatRequest:
    return InternalChatRequest(
        query=query,
        session_id="persistent-session",
        memory_context=MemoryContextInput(
            actor=InternalActor(user_id="user-1", authenticated=True),
            chat_id="persistent-session",
            revision=1,
            current_message_id="message-3",
            current_sequence=3,
            snapshot=MemorySnapshotInput(
                id="snapshot-1",
                version=1,
                revision=1,
                covered_to_sequence=1,
                summary="Earlier discussion summary.",
            ),
            facts=facts or [],
            tail=[
                MemoryMessage(
                    id="message-2",
                    sequence=2,
                    revision=1,
                    role="assistant",
                    content="Earlier answer.",
                )
            ],
        ),
    )
