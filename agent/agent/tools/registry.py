import logging
from collections.abc import Callable, Iterable
from typing import Any

from agent.config.settings import settings
from toolset.tool_layer import BaseTool, get_tools


class InvalidToolError(ValueError):
    """Raised when an object does not satisfy the Agent tool contract."""


class DuplicateToolError(ValueError):
    """Raised when a tool name is registered more than once."""


ToolLoader = Callable[[], BaseTool | Iterable[BaseTool] | None]


class ToolRegistry:
    """Agent-owned registry that adapts tools supplied by the Toolset layer.

    The registry exposes the CP2 interface while retaining aliases used by the
    existing Agent implementation. Tool implementations remain owned by the
    Toolset layer.
    """

    def __init__(
        self,
        tools: Iterable[BaseTool] | None = None,
        *,
        loaders: Iterable[ToolLoader] | None = None,
        logger: logging.Logger | None = None,
        autoload: bool | None = None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._loaders = list(loaders or [])
        self._logger = logger or logging.getLogger("agent-layer.tools")

        if tools is not None:
            for tool in tools:
                self.register(tool)
            return

        should_autoload = (
            settings.TOOL_AUTOLOAD_ENABLED if autoload is None else autoload
        )
        if should_autoload:
            self.load_tools()

    def register(self, tool: BaseTool, *, overwrite: bool = False) -> None:
        """Register one tool, rejecting duplicate names unless opted in."""
        self._validate_tool(tool)
        name = tool.name.strip()

        if name in self._tools and not overwrite:
            raise DuplicateToolError(f"tool already registered: {name}")

        action = "replaced" if name in self._tools else "registered"
        self._tools[name] = tool
        self._logger.info("[TOOL_REGISTRY] action=%s name=%s", action, name)

    def unregister(self, name: str) -> None:
        """Remove a tool by name.

        Missing names are treated as a caller error so configuration mistakes
        do not pass silently.
        """
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name}")
        del self._tools[name]
        self._logger.info("[TOOL_REGISTRY] action=unregistered name=%s", name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def load_tools(
        self,
        loaders: Iterable[ToolLoader] | None = None,
    ) -> list[str]:
        """Load Toolset defaults and optional loaders with failure isolation.

        Returns human-readable errors for observability. A failed loader or
        invalid tool does not prevent later loaders from being attempted.
        """
        errors: list[str] = []
        active_loaders = list(loaders) if loaders is not None else self._loaders
        if not active_loaders:
            active_loaders = [get_tools]

        for loader in active_loaders:
            loader_name = getattr(loader, "__name__", loader.__class__.__name__)
            try:
                loaded = loader()
                candidates = self._normalize_loaded_tools(loaded)
                for tool in candidates:
                    try:
                        self.register(tool)
                    except Exception as exc:
                        self._record_load_error(errors, loader_name, exc)
            except Exception as exc:
                self._record_load_error(errors, loader_name, exc)

        return errors

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        return [self._to_openai_schema(tool) for tool in self._tools.values()]

    def list_tool_metadata(self) -> list[dict[str, Any]]:
        """Return the stable public representation used by ``GET /api/tools``."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "enabled": bool(getattr(tool, "enabled", True)),
            }
            for tool in self._tools.values()
        ]

    # Backward-compatible aliases used by the current Agent implementation.
    def register_tool(self, tool: BaseTool) -> None:
        self.register(tool)

    def unregister_tool(self, name: str) -> None:
        self.unregister(name)

    def get_tool(self, name: str) -> BaseTool | None:
        return self.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        return self.list_tools()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return self.to_openai_schemas()

    @staticmethod
    def _validate_tool(tool: Any) -> None:
        name = getattr(tool, "name", None)
        description = getattr(tool, "description", None)
        parameters = getattr(tool, "parameters", None)

        if not isinstance(name, str) or not name.strip():
            raise InvalidToolError("tool name must be a non-empty string")
        if not isinstance(description, str):
            raise InvalidToolError(f"tool {name!r} description must be a string")
        if not isinstance(parameters, dict):
            raise InvalidToolError(f"tool {name!r} parameters must be a dict")
        if not callable(getattr(tool, "execute", None)):
            raise InvalidToolError(f"tool {name!r} must define execute(**kwargs)")

    @staticmethod
    def _normalize_loaded_tools(
        loaded: BaseTool | Iterable[BaseTool] | None,
    ) -> list[BaseTool]:
        if loaded is None:
            return []
        if isinstance(loaded, BaseTool):
            return [loaded]
        if isinstance(loaded, (str, bytes, dict)):
            raise InvalidToolError("tool loader must return a tool or iterable of tools")
        return list(loaded)

    @staticmethod
    def _to_openai_schema(tool: BaseTool) -> dict[str, Any]:
        schema_builder = getattr(tool, "to_openai_schema", None)
        if callable(schema_builder):
            return schema_builder()
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _record_load_error(
        self,
        errors: list[str],
        loader_name: str,
        exc: Exception,
    ) -> None:
        message = f"{loader_name}: {exc}"
        errors.append(message)
        self._logger.warning(
            "[TOOL_REGISTRY] action=load_failed loader=%s error=%s",
            loader_name,
            exc,
        )
