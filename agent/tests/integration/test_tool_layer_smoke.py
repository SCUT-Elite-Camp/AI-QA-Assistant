from tests.grounding_helpers import grounded_content
import json
from agent.config.settings import settings
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from agent.agent import Agent


def test_real_tool_layer_smoke_path(monkeypatch) -> None:
    from agent.llm.llm_client import LLMClient
    monkeypatch.setattr(LLMClient, "chat", lambda *args, **kwargs: {"content": json.dumps({
        "claims": [{"text": "Q1 focuses on a single-turn RAG Agent flow.",
                    "supports": [{"citation_id": 1, "quote": "Q1 focuses on a single-turn RAG Agent flow."}]}],
    })})
    monkeypatch.setattr(settings, "MIN_RETRIEVAL_SCORE", 0.0)

    from toolset.tool_layer import SearchTool
    def mock_search(*args, **kwargs):
        return [
            {
                "doc_id": "doc_001",
                "chunk_id": "doc_001::chunk_0",
                "chunk_index": 0,
                "chunk_text": (
                    "Q1 focuses on a single-turn RAG Agent flow. "
                    "The Agent Layer receives a user query, calls retrieval once, "
                    "builds a prompt, calls the LLM, and returns an answer with citations."
                ),
                "title": "Q1 Project Goals",
                "score": 0.92,
                "source_url": "",
            }
        ]
    monkeypatch.setattr(SearchTool, "search", mock_search)

    response = Agent().chat(
        ChatRequest(
            query="What does the Tool Layer CP1 interface return?",
            top_k=2,
            retrieval_mode="hybrid",
        )
    )

    assert response.status == StatusCode.SUCCESS
    assert response.trace_id.startswith("trace-")
    assert response.citations
    assert response.citations[0].doc_id == "doc_001"
    assert response.citations[0].chunk_id == "doc_001_chunk_0"
