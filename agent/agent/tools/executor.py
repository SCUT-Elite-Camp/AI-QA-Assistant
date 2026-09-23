import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import copy_context
from typing import Any, Callable

from pydantic import ValidationError

from agent.config.settings import settings
from agent.schemas.tool_execution import Evidence, ToolExecutionResult
from agent.tools.registry import ToolRegistryAdapter
from toolset.tool_layer import BaseTool


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
            parsed_arguments = self._parse_arguments(arguments)
            self._validate_arguments(tool.parameters, parsed_arguments)
        except ValueError as exc:
            return self._failure(
                tool_call_id,
                tool_name,
                "invalid_arguments",
                str(exc),
                started,
            )

        try:
            if tool.name == "search_documents" and callable(
                getattr(tool, "search", None)
            ):
                operation = lambda: self._execute_search(
                    tool,
                    parsed_arguments,
                    trace_id,
                    retrieval_attempt,
                )
            elif tool.name in {"find_documents", "get_document"}:
                operation = lambda: self._execute_document_tool(
                    tool,
                    parsed_arguments,
                    retrieval_attempt,
                )
            elif tool.name == "search_library":
                operation = lambda: self._execute_library_tool(
                    tool,
                    parsed_arguments,
                    retrieval_attempt,
                )
            else:
                operation = lambda: self._execute_generic(tool, parsed_arguments)

            data, evidence = self._run_with_timeout(operation)
        except FutureTimeout:
            return self._failure(
                tool_call_id,
                tool_name,
                "tool_timeout",
                f"Tool execution exceeded {self.timeout_ms} ms.",
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
                    if tool_name == "search_documents"
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

    def _run_with_timeout(
        self,
        operation: Callable[[], tuple[dict[str, Any] | None, list[Evidence]]],
    ) -> tuple[dict[str, Any] | None, list[Evidence]]:
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-tool")
        future = pool.submit(copy_context().run, operation)
        try:
            return future.result(timeout=self.timeout_ms / 1000)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _execute_generic(
        tool: BaseTool,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[Evidence]]:
        raw_result = tool.execute(**arguments)
        if isinstance(raw_result, dict):
            data = raw_result
        else:
            data = {"result": raw_result}
        return data, []

    @staticmethod
    def _execute_search(
        tool: BaseTool,
        arguments: dict[str, Any],
        trace_id: str,
        retrieval_attempt: int,
    ) -> tuple[dict[str, Any], list[Evidence]]:
        query = arguments["query"]
        mode = arguments.get("mode", "hybrid")
        top_k = arguments.get("top_k", 5)
        filters = arguments.get("filters")
        min_score = float(getattr(tool, "min_score", 0.0))

        rows = tool.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            min_score=min_score,
            trace_id=trace_id,
        )
        evidence = [
            Evidence(
                doc_id=row["doc_id"],
                chunk_id=row["chunk_id"],
                chunk_index=row.get("chunk_index", 0),
                title=row["title"],
                content=row.get("chunk_text", row.get("content", "")),
                source_url=row.get("source_url", ""),
                score=row["score"],
                retrieval_query=query,
                retrieval_mode=mode,
                retrieval_attempt=retrieval_attempt,
            )
            for row in rows
        ]
        return {"result_count": len(evidence)}, evidence

    @staticmethod
    def _execute_document_tool(
        tool: BaseTool,
        arguments: dict[str, Any],
        retrieval_attempt: int,
    ) -> tuple[dict[str, Any], list[Evidence]]:
        data = tool.execute(**arguments)
        if not isinstance(data, dict):
            raise ValueError("document tools must return a dictionary")

        evidence: list[Evidence] = []
        if tool.name == "find_documents":
            query = str(arguments.get("query") or "document search")
            for document in data.get("documents", []):
                if not isinstance(document, dict):
                    continue
                doc_id = str(document.get("doc_id") or "")
                summary = str(
                    document.get("match_summary") or document.get("title") or ""
                ).strip()
                if not doc_id or not summary:
                    continue
                evidence.append(Evidence(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}::document",
                    chunk_index=0,
                    title=str(document.get("title") or doc_id),
                    content=summary,
                    source_url=str(document.get("source_url") or ""),
                    score=min(1.0, max(0.0, float(document.get("score", 0.0)))),
                    retrieval_query=query,
                    retrieval_mode="document",
                    retrieval_attempt=retrieval_attempt,
                ))
        elif "error" not in data:
            document = data.get("document") or {}
            if not isinstance(document, dict):
                raise ValueError("get_document must return document metadata")
            doc_id = str(document.get("doc_id") or arguments.get("doc_id") or "")
            title = str(document.get("title") or doc_id)
            for chunk in data.get("chunks", []):
                if not isinstance(chunk, dict):
                    continue
                index = int(chunk.get("index", 0))
                content = str(chunk.get("text") or "").strip()
                if not doc_id or not content:
                    continue
                evidence.append(Evidence(
                    doc_id=doc_id,
                    chunk_id=str(chunk.get("chunk_id") or f"{doc_id}::chunk_{index}"),
                    chunk_index=index,
                    title=title,
                    content=content,
                    source_url=str(document.get("source_url") or ""),
                    score=1.0,
                    retrieval_query=doc_id,
                    retrieval_mode="document",
                    retrieval_attempt=retrieval_attempt,
                ))
        return data, evidence

    @staticmethod
    def _execute_library_tool(
        tool: BaseTool,
        arguments: dict[str, Any],
        retrieval_attempt: int,
    ) -> tuple[dict[str, Any], list[Evidence]]:
        data = tool.execute(**arguments)
        if not isinstance(data, dict):
            raise ValueError("search_library must return a dictionary")

        query = str(arguments.get("query") or "personal library search")
        mode = str(arguments.get("mode") or "hybrid")
        evidence: list[Evidence] = []
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            document_id = str(item.get("document_id") or "")
            evidence_id = str(item.get("evidence_id") or "")
            content = str(item.get("content") or "").strip()
            if not document_id or not evidence_id or not content:
                continue
            evidence.append(Evidence(
                doc_id=document_id,
                chunk_id=evidence_id,
                chunk_index=max(0, int(item.get("chunk_index", 0))),
                title=str(item.get("filename") or document_id),
                content=content,
                source_url=str(item.get("source_url") or ""),
                score=min(1.0, max(0.0, float(item.get("score", 0.0)))),
                retrieval_query=query,
                retrieval_mode=mode,
                retrieval_attempt=retrieval_attempt,
                source_type="personal",
                evidence_id=evidence_id,
                locator=(item.get("locator") if isinstance(item.get("locator"), dict) else None),
                source_scope=str(item.get("source_scope") or "personal"),
                knowledge_base_id=str(item.get("knowledge_base_id") or "") or None,
                document_id=document_id,
                version_id=str(item.get("version_id") or "") or None,
            ))
        return data, evidence

    @staticmethod
    def _parse_arguments(arguments: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return dict(arguments)
        if not isinstance(arguments, str):
            raise ValueError("arguments must be a JSON object or dictionary")
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("arguments are not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("arguments JSON must contain an object")
        return parsed

    @classmethod
    def _validate_arguments(
        cls,
        schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> None:
        if schema.get("type", "object") != "object":
            raise ValueError("tool parameter schema must describe an object")

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(
                f"missing required argument(s): {', '.join(sorted(missing))}"
            )

        if schema.get("additionalProperties") is False:
            unknown = sorted(set(arguments) - set(properties))
            if unknown:
                raise ValueError(f"unknown argument(s): {', '.join(unknown)}")

        for name, value in arguments.items():
            field_schema = properties.get(name)
            if not field_schema:
                continue
            cls._validate_value(name, value, field_schema)

    @staticmethod
    def _validate_value(
        name: str,
        value: Any,
        schema: dict[str, Any],
    ) -> None:
        expected = schema.get("type")
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        python_type = type_map.get(expected)
        if python_type is not None:
            type_matches = isinstance(value, python_type)
            if expected in {"integer", "number"} and isinstance(value, bool):
                type_matches = False
            if not type_matches:
                raise ValueError(f"argument '{name}' must be {expected}")

        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"argument '{name}' is not an allowed value")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"argument '{name}' is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"argument '{name}' exceeds the maximum")

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
