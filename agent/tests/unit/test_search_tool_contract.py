from typing import Any

import pytest

from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry
from toolset.tool_layer.search_tool import SearchTool


pytestmark = pytest.mark.no_storage


def test_canonical_search_tool_uses_canonical_base_tool() -> None:
    assert issubclass(SearchTool, BaseTool)


class Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return []


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "query", "top_k": 0},
        {"query": "query", "top_k": 21},
        {"query": "query", "mode": "dense"},
    ],
)
def test_search_schema_rejects_invalid_constraints_before_retrieval(
    arguments: dict[str, Any],
) -> None:
    backend = Backend()
    registry = ToolsetRegistry(tools=[SearchTool(backend=backend)])
    executor = ToolExecutor(ToolRegistryAdapter(registry), timeout_ms=1000)

    result = executor.execute(
        tool_call_id="call-invalid-search",
        tool_name="search_documents",
        arguments=arguments,
        trace_id="trace-invalid-search",
    )

    assert result.success is False
    assert result.error_code == "invalid_arguments"
    assert backend.calls == []
