from agent.config.settings import settings
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from agent.service.chat_service import ChatService


def test_real_tool_layer_smoke_path(monkeypatch) -> None:
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

    response = ChatService().chat(
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
    assert response.citations[0].chunk_id == "doc_001::chunk_0"
