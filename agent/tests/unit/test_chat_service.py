from agent.llm.mock_llm import MockLLM
from agent.schemas.retrieval import RetrievalResult
from agent.retrieval.mock_retrieval import MockRetrieval
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from agent.service.chat_service import ChatService


def test_normal_query_returns_success() -> None:
    response = ChatService().chat(ChatRequest(query="项目 Q1 阶段需要完成哪些功能？"))

    assert response.status == StatusCode.SUCCESS
    assert response.answer
    assert response.citations
    assert response.trace_id.startswith("trace-")


def test_empty_query_returns_invalid_query() -> None:
    response = ChatService().chat(ChatRequest(query="   "))

    assert response.status == StatusCode.INVALID_QUERY
    assert response.answer == ""
    assert response.message == "请输入有效问题。"
    assert response.citations == []


def test_empty_retrieval_returns_no_relevant_context() -> None:
    service = ChatService(retriever=MockRetrieval(return_empty=True))

    response = service.chat(ChatRequest(query="知识库外问题"))

    assert response.status == StatusCode.NO_RELEVANT_CONTEXT
    assert response.answer == ""
    assert response.citations == []


def test_retrieval_error_returns_retrieval_error() -> None:
    service = ChatService(retriever=MockRetrieval(should_raise=True))

    response = service.chat(ChatRequest(query="触发检索异常"))

    assert response.status == StatusCode.RETRIEVAL_ERROR
    assert response.message == "检索服务暂时不可用，请稍后重试。"


def test_llm_error_returns_llm_error() -> None:
    service = ChatService(llm=MockLLM(should_raise=True))

    response = service.chat(ChatRequest(query="触发模型异常"))

    assert response.status == StatusCode.LLM_ERROR
    assert response.message == "模型服务暂时不可用，请稍后重试。"


class RecordingRetriever:
    def __init__(self) -> None:
        self.last_call = {}

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
        mode: str = "hybrid",
        min_score: float = 0.0,
        trace_id: str | None = None,
    ) -> list[RetrievalResult]:
        self.last_call = {
            "query": query,
            "top_k": top_k,
            "filters": filters,
            "mode": mode,
            "min_score": min_score,
            "trace_id": trace_id,
        }
        return [
            RetrievalResult(
                doc_id="doc-1",
                chunk_id="doc-1::chunk_0",
                chunk_index=0,
                chunk_text="测试上下文",
                title="测试文档",
                source_url="",
                score=0.9,
            )
        ]


def test_chat_service_passes_week2_retrieval_parameters() -> None:
    retriever = RecordingRetriever()
    service = ChatService(retriever=retriever)

    response = service.chat(
        ChatRequest(
            query="  第二周做什么？ ",
            top_k=3,
            filters={"doc_type": "md"},
            retrieval_mode="bm25",
        )
    )

    assert response.status == StatusCode.SUCCESS
    assert retriever.last_call["query"] == "第二周做什么？"
    assert retriever.last_call["top_k"] == 3
    assert retriever.last_call["filters"] == {"doc_type": "md"}
    assert retriever.last_call["mode"] == "bm25"
    assert retriever.last_call["trace_id"].startswith("trace-")


def test_chat_service_returns_retrieval_error_when_real_tool_missing(monkeypatch) -> None:
    monkeypatch.setattr("agent.retrieval.retrieval_adapter.settings.USE_MOCK_RETRIEVAL", False)
    monkeypatch.setattr("agent.retrieval.retrieval_adapter.settings.TOOL_LAYER_IMPORT", "missing_tool_layer")

    service = ChatService()
    response = service.chat(ChatRequest(query="真实检索冒烟"))

    assert response.status == StatusCode.RETRIEVAL_ERROR
    assert response.answer == ""
    assert response.message == "检索服务暂时不可用，请稍后重试。"
