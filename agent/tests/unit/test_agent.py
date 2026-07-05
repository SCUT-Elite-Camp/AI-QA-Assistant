from unittest.mock import MagicMock
import pytest
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult
from agent.agent import Agent
from agent.llm.llm_client import LLMClient
from toolset.tool_layer.search_tool import SearchTool
from agent.errors.exceptions import LLMError


def test_normal_query_returns_success() -> None:
    # LLMClient.chat is mocked by conftest fixture autouse
    response = Agent().chat(ChatRequest(query="项目 Q1 阶段需要完成哪些功能？"))

    assert response.status == StatusCode.SUCCESS
    assert response.answer
    assert len(response.citations) > 0
    assert response.trace_id.startswith("trace-")


def test_empty_query_returns_invalid_query() -> None:
    response = Agent().chat(ChatRequest(query="   "))

    assert response.status == StatusCode.INVALID_QUERY
    assert response.answer == ""
    assert response.message == "请输入有效问题。"
    assert response.citations == []


def test_empty_retrieval_returns_no_relevant_context(monkeypatch) -> None:
    # Mock SearchTool.search to return empty list
    monkeypatch.setattr(SearchTool, "search", lambda *args, **kwargs: [])

    response = Agent().chat(ChatRequest(query="知识库外问题"))

    assert response.status == StatusCode.NO_RELEVANT_CONTEXT
    assert response.answer == ""
    assert response.citations == []


def test_retrieval_error_returns_retrieval_error(monkeypatch) -> None:
    # Mock SearchTool.search to raise an error
    def mock_raise(*args, **kwargs):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(SearchTool, "search", mock_raise)

    response = Agent().chat(ChatRequest(query="触发检索异常"))

    assert response.status in (StatusCode.LLM_ERROR, StatusCode.RETRIEVAL_ERROR)
    assert response.answer == ""


def test_llm_error_returns_llm_error(monkeypatch) -> None:
    # Mock LLMClient.chat to raise an exception
    def mock_chat_raise(*args, **kwargs):
        raise LLMError("LLM disconnect")
    monkeypatch.setattr(LLMClient, "chat", mock_chat_raise)

    response = Agent().chat(ChatRequest(query="触发模型异常"))

    assert response.status == StatusCode.LLM_ERROR
    assert response.message == "服务异常，请稍后重试。"


def test_chat_service_passes_week2_retrieval_parameters(monkeypatch) -> None:
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
            "chunk_text": "测试上下文",
            "title": "测试文档",
            "source_url": "",
            "score": 0.9,
        }]

    monkeypatch.setattr(SearchTool, "search", mock_search)

    response = Agent().chat(
        ChatRequest(
            query="  第二周做什么？ ",
            top_k=3,
            filters={"doc_type": "md"},
            retrieval_mode="bm25",
        )
    )

    assert response.status == StatusCode.SUCCESS
    assert called_params["query"] == "第二周做什么？"


def test_low_score_retrieval_returns_no_relevant_context(monkeypatch) -> None:
    monkeypatch.setattr("agent.config.settings.settings.MIN_RETRIEVAL_SCORE", 0.8)

    # Mock search to return low-score chunk
    def mock_search(*args, **kwargs):
        return [{
            "doc_id": "doc-low",
            "chunk_id": "doc-low::chunk_0",
            "chunk_index": 0,
            "chunk_text": "低相关上下文",
            "title": "低相关文档",
            "source_url": "",
            "score": 0.2,
        }]
    monkeypatch.setattr(SearchTool, "search", mock_search)

    response = Agent().chat(ChatRequest(query="知识库外问题"))

    assert response.status == StatusCode.NO_RELEVANT_CONTEXT
    assert response.answer == ""
    assert response.citations == []


def test_empty_llm_answer_returns_llm_error(monkeypatch) -> None:
    # Mock LLMClient.chat to return empty content
    monkeypatch.setattr(LLMClient, "chat", lambda *args, **kwargs: {"role": "assistant", "content": "   "})

    response = Agent().chat(ChatRequest(query="触发空模型答案"))

    assert response.status == StatusCode.LLM_ERROR
    assert response.answer == ""
    assert response.citations == []
