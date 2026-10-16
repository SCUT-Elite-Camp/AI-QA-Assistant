"""Coordinate validation, authorization and bounded tool execution."""

import logging
import time
from concurrent.futures import TimeoutError as FutureTimeout
from functools import partial
from typing import Any

from pydantic import ValidationError

from agent.config.settings import settings
from agent.schemas.tool_execution import ToolExecutionResult
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.service.permission_service import PermissionResolutionError
from agent.tools.argument_validation import parse_arguments, validate_arguments
from agent.tools.execution_pool import ToolCapacityExhausted, run_with_timeout
from agent.tools.registry import ToolRegistryAdapter
from agent.tools.result_adapters import RETRIEVAL_TOOLS, execute_tool


class ToolExecutor:
    """Validate and execute Toolset-owned tools with request-local results."""

    def __init__(
        self,
        registry: ToolRegistryAdapter,
        *,
        timeout_ms: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.registry = registry
        self.timeout_ms = (
            settings.TOOL_TIMEOUT_MS if timeout_ms is None else timeout_ms
        )
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self.logger = logger or logging.getLogger("agent-layer.tools")

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any] | str,
        trace_id: str,
        retrieval_attempt: int = 1,
        direct_retrieval: bool = False,
    ) -> ToolExecutionResult:
        """Return a structured result for every execution outcome."""
        started = time.perf_counter()

        tool = self.registry.get(tool_name)
        if tool is None:
            return self._failure(
                tool_call_id,
                tool_name,
                "tool_not_found",
                f"Tool '{tool_name}' is not registered.",
                started,
            )

        try:
            parsed_arguments = parse_arguments(arguments)
            validate_arguments(tool.parameters, parsed_arguments)
        except ValueError as exc:
            return self._failure(
                tool_call_id,
                tool_name,
                "invalid_arguments",
                str(exc),
                started,
            )

        try:
            guard = CURRENT_ACCESS_GUARD.get()
            if guard is not None:
                parsed_arguments = guard.prepare_tool(tool.name, parsed_arguments)
            operation = partial(
                execute_tool, tool, parsed_arguments,
                trace_id=trace_id, retrieval_attempt=retrieval_attempt,
                direct_retrieval=direct_retrieval,
            )

            timeout_ms = self.timeout_ms
            from retrieval.reranker import BEFORE_RERANK
            checker = (lambda rows: guard.validate_rerank_candidates(tool.name, rows)) if guard is not None else None
            ranking_token = BEFORE_RERANK.set(checker)
            try:
                data, evidence = run_with_timeout(operation, timeout_ms=timeout_ms)
            finally:
                BEFORE_RERANK.reset(ranking_token)
            if guard is not None:
                guard.capture_tool(tool.name, data, evidence)
        except PermissionResolutionError:
            # Authorization failure terminates the turn, not a recoverable tool error.
            raise
        except ToolCapacityExhausted:
            return self._failure(
                tool_call_id,
                tool_name,
                "tool_capacity_exhausted",
                "Tool execution capacity is temporarily exhausted.",
                started,
            )
        except FutureTimeout:
            return self._failure(
                tool_call_id,
                tool_name,
                "tool_timeout",
                f"Tool execution exceeded {timeout_ms} ms.",
                started,
            )
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            return self._failure(
                tool_call_id,
                tool_name,
                "invalid_tool_result",
                str(exc),
                started,
            )
        except Exception as exc:
            self.logger.exception(
                "[TOOL_EXECUTION] trace_id=%s tool_call_id=%s tool=%s error=%s",
                trace_id,
                tool_call_id,
                tool_name,
                exc.__class__.__name__,
            )
            return self._failure(
                tool_call_id,
                tool_name,
                (
                    "retrieval_error"
                    if tool_name in RETRIEVAL_TOOLS
                    else "tool_execution_failed"
                ),
                str(exc) or exc.__class__.__name__,
                started,
            )

        result = ToolExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            success=True,
            data=data,
            evidence=evidence,
            elapsed_ms=self._elapsed_ms(started),
        )
        self.logger.info(
            "[TOOL_EXECUTION] trace_id=%s tool_call_id=%s tool=%s "
            "success=true evidence=%s elapsed_ms=%s",
            trace_id,
            tool_call_id,
            tool_name,
            len(evidence),
            result.elapsed_ms,
        )
        return result

    def _failure(
        self,
        tool_call_id: str,
        tool_name: str,
        error_code: str,
        error_message: str,
        started: float,
    ) -> ToolExecutionResult:
        result = ToolExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            success=False,
            error_code=error_code,
            error_message=error_message,
            elapsed_ms=self._elapsed_ms(started),
        )
        self.logger.warning(
            "[TOOL_EXECUTION] tool_call_id=%s tool=%s success=false "
            "error_code=%s elapsed_ms=%s",
            tool_call_id,
            tool_name,
            error_code,
            result.elapsed_ms,
        )
        return result

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))
