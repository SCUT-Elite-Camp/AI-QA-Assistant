import time
from typing import Any

import pytest

from agent.schemas.tool_execution import Evidence, ToolExecutionResult
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry


pytestmark = pytest.mark.no_storage


class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Return the provided text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> Any:
        return {"echo": kwargs["text"]}


class FailingTool(EchoTool):
    @property
    def name(self) -> str:
        return "failing"

    def execute(self, **kwargs: Any) -> Any:
        raise RuntimeError("tool exploded")


class SlowTool(EchoTool):
    @property
    def name(self) -> str:
        return "slow"

    def execute(self, **kwargs: Any) -> Any:
        time.sleep(0.03)
        return kwargs["text"]


class StructuredSearchTool(BaseTool):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.search_arguments: dict[str, Any] = {}
        self.execute_called = False
        self.latest_results = ["must not be read"]
        self.min_score = 0.2

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Search documents."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "mode": {
                    "type": "string",
                    "enum": ["vector", "bm25", "hybrid"],
                },
                "filters": {"type": "object"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> Any:
        self.execute_called = True
        raise AssertionError("ToolExecutor must use structured search()")

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.search_arguments = kwargs
        return self.rows


def _executor(*tools: BaseTool, timeout_ms: int = 1000) -> ToolExecutor:
    registry = ToolRegistryAdapter(ToolsetRegistry(tools=list(tools)))
    return ToolExecutor(registry, timeout_ms=timeout_ms)


def test_generic_tool_returns_request_local_structured_data() -> None:
    result = _executor(EchoTool()).execute(
        tool_call_id="call-1",
        tool_name="echo",
        arguments='{"text":"hello"}',
        trace_id="trace-1",
    )

    assert result.success is True
    assert result.data == {"echo": "hello"}
    assert result.evidence == []
    assert result.error_code == ""


def test_missing_tool_returns_tool_not_found() -> None:
    result = _executor(EchoTool()).execute(
        tool_call_id="call-2",
        tool_name="missing",
        arguments={},
        trace_id="trace-2",
    )

    assert result.success is False
    assert result.error_code == "tool_not_found"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ('{"text":', "not valid JSON"),
        ([], "JSON object or dictionary"),
        ({}, "missing required"),
        ({"text": 3}, "must be string"),
        ({"text": "ok", "extra": True}, "unknown argument"),
    ],
)
def test_invalid_arguments_are_rejected(
    arguments: Any,
    message: str,
) -> None:
    result = _executor(EchoTool()).execute(
        tool_call_id="call-invalid",
        tool_name="echo",
        arguments=arguments,
        trace_id="trace-invalid",
    )

    assert result.success is False
    assert result.error_code == "invalid_arguments"
    assert message in result.error_message


def test_tool_exception_is_mapped_without_escaping() -> None:
    result = _executor(FailingTool()).execute(
        tool_call_id="call-3",
        tool_name="failing",
        arguments={"text": "hello"},
        trace_id="trace-3",
    )

    assert result.success is False
    assert result.error_code == "tool_execution_failed"
    assert result.error_message == "tool exploded"


def test_tool_timeout_is_mapped() -> None:
    result = _executor(SlowTool(), timeout_ms=5).execute(
        tool_call_id="call-4",
        tool_name="slow",
        arguments={"text": "hello"},
        trace_id="trace-4",
    )

    assert result.success is False
    assert result.error_code == "tool_timeout"


def test_search_uses_structured_result_without_latest_results() -> None:
    tool = StructuredSearchTool(
        [
            {
                "doc_id": "doc-1",
                "chunk_id": "chunk-1",
                "chunk_index": 2,
                "title": "CP2 Plan",
                "chunk_text": "ToolExecutor returns request-local evidence.",
                "source_url": "https://example.test/doc-1",
                "score": 0.87,
            }
        ]
    )
    result = _executor(tool).execute(
        tool_call_id="call-search",
        tool_name="search_documents",
        arguments={
            "query": "How does ToolExecutor work?",
            "top_k": 4,
            "mode": "hybrid",
            "filters": {"space": "CP2"},
        },
        trace_id="trace-search",
        retrieval_attempt=2,
    )

    assert result.success is True
    assert result.data == {"result_count": 1}
    assert result.evidence == [
        Evidence(
            doc_id="doc-1",
            chunk_id="chunk-1",
            chunk_index=2,
            title="CP2 Plan",
            content="ToolExecutor returns request-local evidence.",
            source_url="https://example.test/doc-1",
            score=0.87,
            retrieval_query="How does ToolExecutor work?",
            retrieval_mode="hybrid",
            retrieval_attempt=2,
        )
    ]
    assert tool.execute_called is False
    assert tool.latest_results == ["must not be read"]
    assert tool.search_arguments == {
        "query": "How does ToolExecutor work?",
        "top_k": 4,
        "mode": "hybrid",
        "filters": {"space": "CP2"},
        "min_score": 0.2,
        "trace_id": "trace-search",
    }


def test_invalid_search_row_returns_invalid_tool_result() -> None:
    tool = StructuredSearchTool([{"doc_id": "doc-without-required-fields"}])

    result = _executor(tool).execute(
        tool_call_id="call-bad-search",
        tool_name="search_documents",
        arguments={"query": "test"},
        trace_id="trace-bad-search",
    )

    assert result.success is False
    assert result.error_code == "invalid_tool_result"
    assert result.evidence == []


def test_execution_models_reject_shared_or_invalid_state() -> None:
    first = ToolExecutionResult(
        tool_call_id="call-a",
        tool_name="echo",
        success=True,
    )
    second = ToolExecutionResult(
        tool_call_id="call-b",
        tool_name="echo",
        success=True,
    )

    first.evidence.append(
        Evidence(
            doc_id="doc",
            chunk_id="chunk",
            title="Title",
            content="Content",
            score=1.0,
            retrieval_query="query",
            retrieval_mode="hybrid",
        )
    )

    assert second.evidence == []
