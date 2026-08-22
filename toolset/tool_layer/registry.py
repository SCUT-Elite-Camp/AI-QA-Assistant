from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from .base_tool import BaseTool
from .search_tool import SearchTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _build_default_search_tool() -> SearchTool:
    """构造默认的检索工具。

    注：SearchTool 在权限集成后已简化为内置的 hybrid 检索（bm25 + milvus），
    不再接收 reranker / retrieval_orchestrator 等参数。此前的 orchestrator /
    reranker 构造逻辑已随之移除；如需启用 query 改写 / 重排，应在 SearchTool
    内部或独立的检索编排层实现，而不是在此处注入。
    """
    return SearchTool()


class ToolRegistry:
    """Registry class responsible for maintaining and exposing all tools in the toolset layer.

    It provides interfaces to register tools, query tools, list tools, and retrieve
    tool descriptions/schemas.
    """

    def __init__(self, tools: Optional[List[BaseTool]] = None) -> None:
        self._tools: Dict[str, BaseTool] = {}
        if tools is None:
            # Register default tools in the toolset layer
            default_tools = [_build_default_search_tool()]
        else:
            default_tools = tools

        for tool in default_tools:
            self.register_tool(tool)

    def register_tool(self, tool: BaseTool) -> None:
        """Registers a new tool instance in the registry."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Retrieves a registered tool instance by its name.

        Args:
            name: The name of the tool to retrieve.

        Returns:
            The tool instance if found, otherwise None.
        """
        return self._tools.get(name)

    def get_all_tools(self) -> List[BaseTool]:
        """Returns a list of all registered tool instances.

        Returns:
            A list containing all registered tool instances.
        """
        return list(self._tools.values())

    def get_tool_descriptions(self) -> Dict[str, str]:
        """Returns a mapping of registered tool names to their descriptions.

        Returns:
            A dictionary mapping tool name (str) to tool description (str).
        """
        return {name: tool.description for name, tool in self._tools.items()}

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Returns the schema representations for all registered tools.

        Returns:
            A list of tool schemas in OpenAI function call representation.
        """
        return [tool.to_openai_schema() for tool in self._tools.values()]


# Default global tool registry instance
default_registry = ToolRegistry()


def get_tools() -> List[BaseTool]:
    """Returns instances of all registered tools from the default registry.

    Provides backward compatibility for callers relying on the legacy tool list format.

    Returns:
        A list of registered tool instances.
    """
    return default_registry.get_all_tools()
