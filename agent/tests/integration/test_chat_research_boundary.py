from tests.grounding_helpers import grounded_model, control_response
import json
from typing import Any
from tests.grounding_helpers import grounded_model

from agent.agent import Agent
from agent.llm.base import BaseLLM
from agent.schemas.chat import ChatRequest
from toolset.tool_layer import BaseTool


class ResearchModeToolCallLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        return ""

    @grounded_model
    @grounded_model
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if tools and not any("[TOOL_OBSERVATIONS]" in str(message.get("content", "")) for message in messages):
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
        return control_response("answer") if tools else {"content":"Answer from local evidence [1]."}


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
                "chunk_text": "Local document evidence.",
                "title": "Local test document",
                "source_url": "",
                "score": 0.95,
            }
        ]


def test_model_tool_arguments_cannot_switch_chat_to_research() -> None:
    search = RecordingSearchTool()
    agent = Agent(
        llm=ResearchModeToolCallLLM(),
        tools=[search],
    )

    response = agent.chat(ChatRequest(query="What evidence is in the local document?", top_k=3, weight_mode="thinking"))

    assert response.status == "success"
    assert len(search.calls) == 1
    assert search.calls[0]["mode"] == "hybrid"
    assert search.calls[0]["top_k"] == 3
    assert agent.last_orchestration is not None
    assert agent.last_run_result.budget["model_calls"] == 3
    assert not hasattr(agent.last_orchestration, "chat_route")
