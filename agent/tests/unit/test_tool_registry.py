from typing import Any

import pytest

from agent.tools import ToolRegistryAdapter
from toolset.tool_layer import BaseTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry


pytestmark = pytest.mark.no_storage


class FakeTool(BaseTool):
    def __init__(self, name: str = "fake_tool", *, enabled: bool = True) -> None:
        self._name = name
        self.enabled = enabled

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake tool owned by the Toolset registry."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

    def execute(self, **kwargs: Any) -> Any:
        return kwargs["value"]


def test_adapter_get_delegates_to_toolset_registry() -> None:
    tool = FakeTool()
    owner = ToolsetRegistry(tools=[tool])
    adapter = ToolRegistryAdapter(owner)

    assert adapter.get("fake_tool") is tool
    assert adapter.get("missing_tool") is None


def test_adapter_lists_toolset_owned_tools() -> None:
    first = FakeTool("first_tool")
    second = FakeTool("second_tool")
    owner = ToolsetRegistry(tools=[first, second])
    adapter = ToolRegistryAdapter(owner)

    assert adapter.list_tools() == [first, second]


def test_adapter_does_not_keep_a_second_tool_mapping() -> None:
    adapter = ToolRegistryAdapter(ToolsetRegistry(tools=[FakeTool()]))

    assert "_tools" not in vars(adapter)


def test_toolset_updates_are_immediately_visible_through_adapter() -> None:
    first = FakeTool("first_tool")
    second = FakeTool("second_tool")
    owner = ToolsetRegistry(tools=[first])
    adapter = ToolRegistryAdapter(owner)

    owner.register_tool(second)

    assert adapter.get("second_tool") is second
    assert adapter.list_tools() == [first, second]


def test_openai_schemas_are_generated_by_toolset_registry() -> None:
    tool = FakeTool()
    owner = ToolsetRegistry(tools=[tool])
    adapter = ToolRegistryAdapter(owner)

    assert adapter.to_openai_schemas() == owner.get_tool_schemas()
    assert adapter.to_openai_schemas() == [
        {
            "type": "function",
            "function": {
                "name": "fake_tool",
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
    ]


def test_adapter_exposes_public_tool_metadata() -> None:
    tool = FakeTool(enabled=False)
    adapter = ToolRegistryAdapter(ToolsetRegistry(tools=[tool]))

    assert adapter.list_tool_metadata() == [
        {
            "name": "fake_tool",
            "description": tool.description,
            "parameters": tool.parameters,
            "enabled": False,
        }
    ]


def test_cp1_read_aliases_remain_available() -> None:
    tool = FakeTool()
    owner = ToolsetRegistry(tools=[tool])
    adapter = ToolRegistryAdapter(owner)

    assert adapter.get_tool("fake_tool") is tool
    assert adapter.get_all_tools() == [tool]
    assert adapter.get_tool_schemas() == owner.get_tool_schemas()
