from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from agent.agent import Agent
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry


@dataclass(frozen=True)
class LifecycleSnapshot:
    initialized: bool
    initialization_count: int
    initialization_ms: int
    retrieval_ready: bool
    retrieval_error: str


class ApplicationContainer:
    """Own application-scoped Agent resources and expose a testable factory seam."""

    def __init__(
        self,
        *,
        llm_factory: Callable[[], BaseLLM] = LLMClient,
        registry_factory: Callable[[], ToolsetRegistry] = ToolsetRegistry,
    ) -> None:
        self._llm_factory = llm_factory
        self._registry_factory = registry_factory
        self._lock = threading.RLock()
        self._agent: Agent | None = None
        self._registry: ToolsetRegistry | None = None
        self._initialization_count = 0
        self._initialization_ms = 0
        self._retrieval_ready = False
        self._retrieval_error = ""

    def startup(self) -> Agent:
        """Initialize shared resources exactly once and return the shared Agent."""
        with self._lock:
            if self._agent is not None:
                return self._agent

            started = time.perf_counter()
            registry = self._registry_factory()
            llm = self._llm_factory()
            self._agent = Agent(llm=llm, toolset_registry=registry)
            self._registry = registry
            self._initialization_count += 1
            self._initialization_ms = max(
                0,
                int((time.perf_counter() - started) * 1000),
            )
            return self._agent

    def get_agent(self) -> Agent:
        """Return the application Agent, lazily starting for non-ASGI callers."""
        return self.startup()

    def warmup_retrieval(self) -> None:
        """Warm the shared search tool without constructing a second registry/tool."""
        agent = self.startup()
        search_tool = agent.registry.get_tool("search_documents")
        if search_tool is None or not callable(getattr(search_tool, "search", None)):
            with self._lock:
                self._retrieval_error = "search_documents is not registered"
            return

        try:
            search_tool.search(
                query="企业智能问答助手",
                top_k=1,
                mode="hybrid",
                filters=None,
                min_score=0.0,
                trace_id="startup-preload",
            )
        except Exception as exc:
            with self._lock:
                self._retrieval_ready = False
                self._retrieval_error = str(exc) or exc.__class__.__name__
            return

        with self._lock:
            self._retrieval_ready = True
            self._retrieval_error = ""

    def snapshot(self) -> LifecycleSnapshot:
        with self._lock:
            return LifecycleSnapshot(
                initialized=self._agent is not None,
                initialization_count=self._initialization_count,
                initialization_ms=self._initialization_ms,
                retrieval_ready=self._retrieval_ready,
                retrieval_error=self._retrieval_error,
            )

    def shutdown(self) -> None:
        """Release container references; provider-owned clients may add close hooks later."""
        with self._lock:
            self._agent = None
            self._registry = None
            self._retrieval_ready = False
            self._retrieval_error = ""


_default_container = ApplicationContainer()


def get_application_container() -> ApplicationContainer:
    return _default_container

