import pytest

from agent.errors.exceptions import RetrievalError
from agent.retrieval.mock_retrieval import MockRetrieval
from agent.retrieval.retrieval_adapter import RetrievalAdapter


def test_retrieval_adapter_wraps_mock_retrieval() -> None:
    adapter = RetrievalAdapter(retriever=MockRetrieval())

    results = adapter.retrieve(query="测试", top_k=2)

    assert len(results) == 2
    assert results[0].doc_id


class FakeSearchTool:
    def __init__(self) -> None:
        self.last_call = {}

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        filters: dict | None = None,
        min_score: float = 0.0,
        trace_id: str | None = None,
    ) -> list[dict]:
        self.last_call = {
            "query": query,
            "top_k": top_k,
            "mode": mode,
            "filters": filters,
            "min_score": min_score,
            "trace_id": trace_id,
        }
        return [
            {
                "doc_id": "doc_001",
                "chunk_index": 0,
                "chunk_text": "retrieved chunk text",
                "score": 0.85,
            }
        ]


class FailingSearchTool:
    def search(self, **kwargs: object) -> list[dict]:
        raise RuntimeError("backend down")


def test_retrieval_adapter_calls_tool_layer_search_interface() -> None:
    search_tool = FakeSearchTool()
    adapter = RetrievalAdapter(retriever=search_tool)

    results = adapter.retrieve(
        query="user question",
        top_k=5,
        filters={"space": "demo"},
        mode="hybrid",
        min_score=0.5,
        trace_id="trace-test",
    )

    assert search_tool.last_call == {
        "query": "user question",
        "top_k": 5,
        "mode": "hybrid",
        "filters": {"space": "demo"},
        "min_score": 0.5,
        "trace_id": "trace-test",
    }
    assert results[0].doc_id == "doc_001"
    assert results[0].chunk_id == "doc_001::chunk_0"
    assert results[0].title == "doc_001"
    assert results[0].chunk_text == "retrieved chunk text"


def test_retrieval_adapter_filters_by_min_score() -> None:
    adapter = RetrievalAdapter(retriever=FakeSearchTool())

    results = adapter.retrieve(query="低分过滤", min_score=0.9)

    assert results == []


def test_retrieval_adapter_maps_search_tool_errors() -> None:
    adapter = RetrievalAdapter(retriever=FailingSearchTool())

    with pytest.raises(RetrievalError):
        adapter.retrieve(query="触发检索异常")


def test_retrieval_adapter_defers_real_tool_layer_loading(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.retrieval.retrieval_adapter.settings.TOOL_LAYER_IMPORT",
        "missing_tool_layer_for_test",
    )
    adapter = RetrievalAdapter(use_mock=False)

    with pytest.raises(RetrievalError):
        adapter.retrieve(query="真实模式但 tool_layer 未安装")


def test_retrieval_adapter_logs_start_and_end(caplog) -> None:
    adapter = RetrievalAdapter(use_mock=True)

    with caplog.at_level("INFO"):
        results = adapter.retrieve(
            query="test query",
            top_k=2,
            trace_id="trace-log-001",
        )

    assert len(results) == 2

    log_text = caplog.text
    assert "[RETRIEVAL_START]" in log_text
    assert "[RETRIEVAL_END]" in log_text
    assert "trace-log-001" in log_text
    assert "results_count=2" in log_text


def test_retrieval_adapter_logs_error_with_trace_id(caplog) -> None:
    adapter = RetrievalAdapter(use_mock=True)

    with caplog.at_level("ERROR"):
        with pytest.raises(RetrievalError):
            adapter.retrieve(
                query="test query",
                mode="invalid_mode",
                trace_id="trace-error-001",
            )

    log_text = caplog.text
    assert "[RETRIEVAL_ERROR]" in log_text
    assert "trace-error-001" in log_text
    assert "Unsupported retrieval mode" in log_text
