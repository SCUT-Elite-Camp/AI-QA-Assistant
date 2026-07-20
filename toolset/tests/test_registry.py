import unittest
from typing import Any, Dict
from tool_layer.base_tool import BaseTool
from tool_layer.registry import ToolRegistry, get_tools


class FakeCustomTool(BaseTool):
    """A fake tool used to test ToolRegistry functionality."""

    @property
    def name(self) -> str:
        return "fake_custom_tool"

    @property
    def description(self) -> str:
        return "A custom tool for testing."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_arg": {
                    "type": "string",
                    "description": "An input argument."
                }
            },
            "required": ["input_arg"]
        }

    def execute(self, **kwargs: Any) -> Any:
        return f"Executed with {kwargs.get('input_arg')}"


class ToolRegistryTest(unittest.TestCase):
    """Unit tests for the ToolRegistry class and registry helper functions."""

    def test_default_registry_initialization(self) -> None:
        registry = ToolRegistry()
        tools = registry.get_all_tools()
        # By default, should have SearchTool registered
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "search_documents")

    def test_custom_registry_initialization(self) -> None:
        fake_tool = FakeCustomTool()
        registry = ToolRegistry(tools=[fake_tool])
        tools = registry.get_all_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "fake_custom_tool")

    def test_register_and_get_tool(self) -> None:
        registry = ToolRegistry(tools=[])
        self.assertEqual(len(registry.get_all_tools()), 0)

        fake_tool = FakeCustomTool()
        registry.register_tool(fake_tool)

        self.assertEqual(len(registry.get_all_tools()), 1)
        retrieved = registry.get_tool("fake_custom_tool")
        self.assertIs(retrieved, fake_tool)

        # Get non-existent tool
        self.assertIsNone(registry.get_tool("non_existent"))

    def test_get_tool_descriptions(self) -> None:
        fake_tool = FakeCustomTool()
        registry = ToolRegistry(tools=[fake_tool])

        descriptions = registry.get_tool_descriptions()
        self.assertEqual(descriptions, {"fake_custom_tool": "A custom tool for testing."})

    def test_get_tool_schemas(self) -> None:
        fake_tool = FakeCustomTool()
        registry = ToolRegistry(tools=[fake_tool])

        schemas = registry.get_tool_schemas()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertEqual(schemas[0]["function"]["name"], "fake_custom_tool")
        self.assertEqual(schemas[0]["function"]["description"], "A custom tool for testing.")
        self.assertEqual(schemas[0]["function"]["parameters"], fake_tool.parameters)

    def test_get_tools_backward_compatibility(self) -> None:
        tools = get_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "search_documents")


if __name__ == "__main__":
    unittest.main()
