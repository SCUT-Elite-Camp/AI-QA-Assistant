from typing import Any

from toolset.tool_layer import BaseTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry


class ToolRegistryAdapter:
    """Read-only Agent adapter over the Toolset-owned ToolRegistry.

    The adapter never stores a second tool mapping. Registration, removal,
    duplicate handling, and tool loading remain responsibilities of Toolset.
    """

    def __init__(self, registry: ToolsetRegistry) -> None:
        self._registry = registry

    def get(self, name: str) -> BaseTool | None:
        """Return the tool currently registered by Toolset."""
        return self._registry.get_tool(name)

    def list_tools(self) -> list[BaseTool]:
        """Return the current Toolset registry view."""
        return self._registry.get_all_tools()

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        """Return Toolset-generated OpenAI function schemas."""
        return self._registry.get_tool_schemas()

    def list_tool_metadata(self) -> list[dict[str, Any]]:
        """Return public metadata without taking ownership of tool state."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "enabled": bool(getattr(tool, "enabled", True)),
            }
            for tool in self._registry.get_all_tools()
        ]

    # Temporary aliases for the existing CP1 Agent implementation.
    def get_tool(self, name: str) -> BaseTool | None:
        return self.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        return self.list_tools()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return self.to_openai_schemas()
