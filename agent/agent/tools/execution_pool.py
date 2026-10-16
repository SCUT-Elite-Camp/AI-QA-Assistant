"""Limit process-wide queued and running tool work; propagate request context."""

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import copy_context
from threading import BoundedSemaphore
from typing import Any, Callable

from agent.config.settings import settings


class ToolCapacityExhausted(RuntimeError):
    """Raised when all process-wide tool execution slots are occupied."""


class _BoundedToolExecutor:
    """Share a fixed worker pool and bound queued plus running tool work."""

    def __init__(self, max_workers: int, max_pending: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-tool",
        )
        self._capacity = BoundedSemaphore(max_workers + max_pending)

    def submit(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future:
        if not self._capacity.acquire(blocking=False):
            raise ToolCapacityExhausted("tool execution capacity exhausted")
        try:
            future = self._executor.submit(function, *args, **kwargs)
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _future: self._capacity.release())
        return future


_SHARED_TOOL_EXECUTOR = _BoundedToolExecutor(
    max_workers=settings.TOOL_EXECUTOR_MAX_WORKERS,
    max_pending=settings.TOOL_EXECUTOR_MAX_PENDING,
)


def run_with_timeout(operation: Callable[[], Any], *, timeout_ms: int) -> Any:
    """Bound waiting; running threads retain capacity until completion."""
    future = _SHARED_TOOL_EXECUTOR.submit(copy_context().run, operation)
    try:
        return future.result(timeout=timeout_ms / 1000)
    except FutureTimeout:
        # Cancellation prevents queued work from starting, but cannot stop a thread.
        future.cancel()
        raise
