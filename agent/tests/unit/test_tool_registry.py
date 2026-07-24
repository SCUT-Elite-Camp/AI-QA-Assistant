from typing import Any

import pytest

from agent.tools import DuplicateToolError, InvalidToolError, ToolRegistry
from toolset.tool_layer import BaseTool

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
        return "A fake tool used by registry tests."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

    def execute(self, **kwargs: Any) -> Any:
        return kwargs["value"]


def test_register_get_list_and_unregister_tool() -> None:
    registry = ToolRegistry(tools=[])
    tool = FakeTool()

    registry.register(tool)

    assert registry.get("fake_tool") is tool
    assert registry.list_tools() == [tool]

    registry.unregister("fake_tool")

    assert registry.get("fake_tool") is None
    assert registry.list_tools() == []


def test_register_rejects_duplicate_name_by_default() -> None:
    registry = ToolRegistry(tools=[FakeTool()])

    with pytest.raises(DuplicateToolError, match="already registered"):
        registry.register(FakeTool())


def test_register_can_explicitly_overwrite_duplicate_name() -> None:
    original = FakeTool()
    replacement = FakeTool(enabled=False)
    registry = ToolRegistry(tools=[original])

    registry.register(replacement, overwrite=True)

    assert registry.get("fake_tool") is replacement


def test_unregister_rejects_unknown_name() -> None:
    registry = ToolRegistry(tools=[])

    with pytest.raises(KeyError, match="not registered"):
        registry.unregister("missing_tool")


def test_register_rejects_invalid_tool_contract() -> None:
    registry = ToolRegistry(tools=[])

    with pytest.raises(InvalidToolError, match="name"):
        registry.register(object())  # type: ignore[arg-type]


def test_to_openai_schemas_uses_tool_contract() -> None:
    tool = FakeTool()
    registry = ToolRegistry(tools=[tool])

    schemas = registry.to_openai_schemas()

    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "fake_tool",
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
    ]


def test_list_tool_metadata_contains_enabled_state() -> None:
    registry = ToolRegistry(tools=[FakeTool(enabled=False)])

    assert registry.list_tool_metadata() == [
        {
            "name": "fake_tool",
            "description": "A fake tool used by registry tests.",
            "parameters": FakeTool().parameters,
            "enabled": False,
        }
    ]


def test_load_tools_isolates_loader_failures() -> None:
    registry = ToolRegistry(tools=[])

    def broken_loader() -> FakeTool:
        raise RuntimeError("optional dependency missing")

    def working_loader() -> FakeTool:
        return FakeTool()

    errors = registry.load_tools([broken_loader, working_loader])

    assert len(errors) == 1
    assert "broken_loader" in errors[0]
    assert "optional dependency missing" in errors[0]
    assert registry.get("fake_tool") is not None


def test_legacy_method_aliases_remain_available() -> None:
    tool = FakeTool()
    registry = ToolRegistry(tools=[])

    registry.register_tool(tool)

    assert registry.get_tool("fake_tool") is tool
    assert registry.get_all_tools() == [tool]
    assert registry.get_tool_schemas() == registry.to_openai_schemas()
