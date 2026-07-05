from .search_tool import RetrievalError, RetrievalParameterError, SearchTool
from .base_tool import BaseTool


def get_tools() -> list[BaseTool]:
    """Returns instances of all available tools."""
    return [SearchTool()]


__all__ = [
    "RetrievalError",
    "RetrievalParameterError",
    "SearchTool",
    "BaseTool",
    "get_tools",
]
