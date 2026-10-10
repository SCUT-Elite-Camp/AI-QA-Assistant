import unittest
from typing import Any, Dict
from tool_layer.base_tool import BaseTool
from tool_layer.registry import ToolRegistry


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
    """Unit tests for the ToolRegistry class."""

    def test_default_registry_initialization(self) -> None:
        registry = ToolRegistry()
        tools = registry.get_all_tools()
        # By default, should have SearchTool registered
        self.assertTrue(
            {"search_documents", "find_documents", "get_document"}.issubset(
                {tool.name for tool in tools}
            )
        )

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

    def test_register_duplicate_name_raises_without_replacing_tool(self) -> None:
        original = FakeCustomTool()
        registry = ToolRegistry(tools=[original])

        with self.assertRaisesRegex(ValueError, "already registered: fake_custom_tool"):
            registry.register_tool(FakeCustomTool())

        self.assertIs(registry.get_tool("fake_custom_tool"), original)

    def test_constructor_rejects_duplicate_tool_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "already registered: fake_custom_tool"):
            ToolRegistry(tools=[FakeCustomTool(), FakeCustomTool()])

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

if __name__ == "__main__":
    unittest.main()
