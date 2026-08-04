import json
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
        if "查询重写器" in system:
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


class RecordingSearchTool(BaseTool):
    def __init__(self, *, comparison: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.comparison = comparison

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
        self.calls.append(dict(kwargs))
        query = kwargs["query"]
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


def test_comparison_flow_runs_corrective_retrieval_before_final_answer() -> None:
    plan = QueryPlan(
        original_query="比较 A 和 B",
        standalone_query="A 和 B",
        intent=QueryIntent.COMPARISON,
        sub_queries=["A", "B"],
    )
    understanding = FixedQueryUnderstanding(plan)
    llm = PipelineLLM()
    search = RecordingSearchTool(comparison=True)
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
    assert agent.last_orchestration.run_result.retrieval_attempts == 2
    assert [call["query"] for call in search.calls] == ["A 和 B", "A", "B"]
    assert agent.last_citation_check is not None
    assert agent.last_citation_check.valid is True
