import json
from typing import Any

from agent.agent import Agent
from agent.llm.base import BaseLLM
from agent.memory import InMemoryConversationMemory
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryIntent, QueryPlan
from toolset.tool_layer import BaseTool


class FixedChatUnderstanding:
    def analyze(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        *,
        filters: dict[str, Any] | None = None,
    ) -> QueryPlan:
        return QueryPlan(
            original_query=query,
            standalone_query=query.strip(),
            intent=QueryIntent.KNOWLEDGE_QA,
            filters=dict(filters or {}),
        )


class ResearchModeToolCallLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        return ""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if tools and not any(message.get("role") == "tool" for message in messages):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-research-mode",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps(
                                {
                                    "query": "model query",
                                    "mode": "research",
                                    "top_k": 99,
                                }
                            ),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "基于本地证据的答案 [1]"}


class RecordingSearchTool(BaseTool):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Search local test documents."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "mode": {"type": "string"},
                "filters": {"type": "object"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> Any:
        return self.search(**kwargs)

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(dict(kwargs))
        return [
            {
                "doc_id": "local-doc",
                "chunk_id": "local-doc::chunk-0",
                "chunk_index": 0,
                "chunk_text": "本地文档证据。",
                "title": "本地测试文档",
                "source_url": "",
                "score": 0.95,
            }
        ]


def test_model_tool_arguments_cannot_switch_chat_to_research() -> None:
    search = RecordingSearchTool()
    agent = Agent(
        llm=ResearchModeToolCallLLM(),
        tools=[search],
        memory=InMemoryConversationMemory(),
        query_understanding=FixedChatUnderstanding(),  # type: ignore[arg-type]
    )

    response = agent.chat(ChatRequest(query="本地文档有什么证据？", top_k=3))

    assert response.status == "success"
    assert len(search.calls) == 1
    assert search.calls[0]["mode"] == "hybrid"
    assert search.calls[0]["top_k"] == 3
    assert agent.last_orchestration is not None
    assert agent.last_orchestration.chat_route.research_entry_allowed is False
