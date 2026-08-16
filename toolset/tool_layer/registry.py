import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from retrieval.orchestrator import (
    RetrievalOrchestrator,
    RetrievalOrchestratorConfig,
)
from retrieval.reranker import CrossEncoderReranker
from retrieval.query_rewriter import OpenAICompatibleQueryRewriter, RewriteConfig
from retrieval.query_router import QueryRouter

from .base_tool import BaseTool
from .document_tools import FindDocumentsTool, GetDocumentTool
from .search_tool import SearchTool
from .attachment_tools import InspectAttachmentTool, SearchAttachmentsTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_default_search_tool() -> SearchTool:
    rerank_enabled = os.getenv("RERANK_ENABLED", "false").strip().lower()
    reranker = (
        None
        if rerank_enabled in {"0", "false", "no", "off"}
        else CrossEncoderReranker()
    )
    legacy_rewrite = os.getenv("QUERY_REWRITE_ENABLED")
    if legacy_rewrite is not None and os.getenv("RETRIEVAL_EXPANSION_ENABLED") is None:
        logger.warning(
            "QUERY_REWRITE_ENABLED is deprecated for Toolset; "
            "use RETRIEVAL_EXPANSION_ENABLED"
        )
    retrieval_expansion_enabled = (
        _env_bool("RETRIEVAL_EXPANSION_ENABLED")
        if os.getenv("RETRIEVAL_EXPANSION_ENABLED") is not None
        else _env_bool("QUERY_REWRITE_ENABLED")
    )
    cross_language_enabled = _env_bool("CROSS_LANGUAGE_RETRIEVAL_ENABLED")
    enhanced_retrieval = retrieval_expansion_enabled or cross_language_enabled
    rewrite_timeout_ms = _env_int("QUERY_REWRITE_TIMEOUT_MS", 1200, minimum=1)
    rewrite_max_variants = _env_int(
        "QUERY_REWRITE_MAX_VARIANTS", 2, minimum=0, maximum=2
    )
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    rewrite_api_base = (
        os.getenv("QUERY_REWRITE_API_BASE")
        or os.getenv("LLM_API_BASE")
        or os.getenv("OPENAI_API_BASE")
        or ("https://api.deepseek.com" if deepseek_api_key else None)
    )
    rewrite_api_key = (
        os.getenv("QUERY_REWRITE_API_KEY")
        or os.getenv("LLM_API_KEY")
        or (
            deepseek_api_key
            if rewrite_api_base
            and rewrite_api_base.rstrip("/") == "https://api.deepseek.com"
            else os.getenv("OPENAI_API_KEY") or deepseek_api_key
        )
    )
    orchestrator = None
    if enhanced_retrieval:
        rewriter = OpenAICompatibleQueryRewriter(
            RewriteConfig(
                api_base=rewrite_api_base,
                api_key=rewrite_api_key,
                model=(
                    os.getenv("QUERY_REWRITE_MODEL")
                    or os.getenv("LLM_MODEL")
                    or ("deepseek-v4-flash" if deepseek_api_key else None)
                ),
                timeout_ms=rewrite_timeout_ms,
                max_variants=rewrite_max_variants,
                cross_language_enabled=cross_language_enabled,
            )
        )
        orchestrator = RetrievalOrchestrator(
            query_rewriter=rewriter,
            query_router=QueryRouter(),
            config=RetrievalOrchestratorConfig(
                rewrite_timeout_ms=rewrite_timeout_ms,
                rewrite_max_variants=rewrite_max_variants,
                total_budget_ms=2000,
                fusion_candidate_limit=20,
                cross_language_enabled=cross_language_enabled,
                retrieval_expansion_enabled=retrieval_expansion_enabled,
            ),
        )

    return SearchTool(
        reranker=reranker,
        rerank_top_n=20,
        rerank_modes={"hybrid"},
        retrieval_orchestrator=orchestrator,
        backend_timeout_seconds=_env_int(
            "RETRIEVAL_BACKEND_TIMEOUT_MS", 2000, minimum=1
        )
        / 1000.0,
        neighbor_expansion_enabled=_env_bool("NEIGHBOR_EXPANSION_ENABLED"),
    )


def _build_default_tools() -> List[BaseTool]:
    search_tool = _build_default_search_tool()
    tools: List[BaseTool] = [
        search_tool,
        FindDocumentsTool(search_tool),
        GetDocumentTool(search_tool.documents_dir),
    ]
    if _env_bool("ATTACHMENTS_ENABLED"):
        tools.extend([SearchAttachmentsTool(), InspectAttachmentTool()])
    return tools


def _env_int(
    name: str,
    default: int,
    minimum: int,
    maximum: Optional[int] = None,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


class ToolRegistry:
    """Registry class responsible for maintaining and exposing all tools in the toolset layer.

    It provides interfaces to register tools, query tools, list tools, and retrieve
    tool descriptions/schemas.
    """

    def __init__(self, tools: Optional[List[BaseTool]] = None) -> None:
        self._tools: Dict[str, BaseTool] = {}
        if tools is None:
            # Register default tools in the toolset layer
            default_tools = _build_default_tools()
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
