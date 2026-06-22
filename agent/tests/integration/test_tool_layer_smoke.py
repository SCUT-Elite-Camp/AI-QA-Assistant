from agent.config.settings import settings
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from agent.service.chat_service import ChatService


def test_real_tool_layer_smoke_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "USE_MOCK_RETRIEVAL", False)
    monkeypatch.setattr(settings, "TOOL_LAYER_IMPORT", "tool_layer")
    monkeypatch.setattr(settings, "TOOL_LAYER_CLASS", "SearchTool")
    monkeypatch.setattr(settings, "MIN_RETRIEVAL_SCORE", 0.0)

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
