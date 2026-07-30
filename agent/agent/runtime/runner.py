import json
import logging
from typing import Any

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE
from agent.runtime.state import (
    AgentRunResult,
    AgentState,
    StopReason,
    ToolCallRecord,
)
from agent.schemas.query_plan import QueryPlan
from agent.service.audit_service import AuditService
from toolset.tool_layer import SearchTool


logger = logging.getLogger("agent-layer")


class AgentRunner:
    """Bounded ReAct-style runner consuming the frozen CP2 QueryPlan contract."""

    def __init__(
        self,
        llm: BaseLLM,
        registry: Any,
        audit_service: AuditService,
        max_iterations: int | None = None,
        max_repeated_tool_calls: int | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.audit_service = audit_service
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else settings.MAX_AGENT_ITERATIONS
        )
        self.max_repeated_tool_calls = (
            max_repeated_tool_calls
            if max_repeated_tool_calls is not None
            else settings.MAX_REPEATED_TOOL_CALLS
        )

        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.max_repeated_tool_calls < 1:
            raise ValueError("max_repeated_tool_calls must be at least 1")

    def run(
        self,
        query_plan: QueryPlan,
        *,
        history: list[dict[str, Any]] | None = None,
        trace_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        max_iterations: int | None = None,
    ) -> AgentRunResult:
        """Execute a bounded Agent run.

        Retrieval always uses ``query_plan.standalone_query``. The original
        query is retained in the visible conversation and final-answer context.
        """

        if query_plan.needs_clarification:
            return AgentRunResult(
                stop_reason=StopReason.CLARIFICATION_REQUIRED,
                message=query_plan.clarification_question,
            )

        limit = max_iterations if max_iterations is not None else self.max_iterations
        if limit < 1:
            raise ValueError("max_iterations must be at least 1")

        state = AgentState(
            trace_id=trace_id,
            query_plan=query_plan,
            messages=self._build_messages(query_plan, history or []),
        )
        schemas = self._tool_schemas()
        last_fingerprint: str | None = None
        repeated_count = 0

        for iteration in range(1, limit + 1):
            state.iteration = iteration
            self.audit_service.log_step(iteration - 1, query_plan.original_query)

            try:
                response = self.llm.chat(state.messages, tools=schemas)
            except Exception as exc:
                logger.exception(
                    "[AGENT_LLM_ERROR] trace_id=%s iteration=%s error=%s",
                    trace_id,
                    iteration,
                    exc,
                )
                return self._result(
                    state,
                    StopReason.LLM_ERROR,
                    message="模型服务暂时不可用，请稍后重试。",
                    error_code=exc.__class__.__name__,
                )

            if not isinstance(response, dict):
                return self._result(
                    state,
                    StopReason.LLM_ERROR,
                    message="模型返回格式无效，无法继续执行。",
                    error_code="invalid_llm_response",
                )

            tool_calls = response.get("tool_calls") or []
            content = response.get("content")
            if not isinstance(tool_calls, list):
                return self._result(
                    state,
                    StopReason.LLM_ERROR,
                    message="模型返回的工具调用格式无效。",
                    error_code="invalid_tool_calls",
                )

            if not tool_calls:
                answer = content.strip() if isinstance(content, str) else ""
                if not answer:
                    return self._result(
                        state,
                        StopReason.LLM_ERROR,
                        message="模型服务暂时不可用，请稍后重试。",
                        error_code="empty_llm_response",
                    )
                state.messages.append(
                    {
                        "role": response.get("role", "assistant"),
                        "content": answer,
                    }
                )
                return self._result(
                    state,
                    StopReason.FINAL_ANSWER,
                    answer=answer,
                )

            state.messages.append(self._assistant_tool_call_message(response, tool_calls))

            for raw_call in tool_calls:
                try:
                    call_id, tool_name, arguments = self._parse_tool_call(raw_call)
                    arguments = self._apply_execution_constraints(
                        tool_name=tool_name,
                        arguments=arguments,
                        query_plan=query_plan,
                        mode=mode,
                        top_k=top_k,
                    )
                except ValueError as exc:
                    state.tool_calls.append(
                        ToolCallRecord(
                            iteration=iteration,
                            tool_call_id=self._tool_call_id(raw_call),
                            tool_name=self._tool_name(raw_call),
                            success=False,
                            error_code="invalid_tool_arguments",
                        )
                    )
                    return self._result(
                        state,
                        StopReason.TOOL_ERROR,
                        message="工具参数格式无效，无法继续执行。",
                        error_code=str(exc),
                    )

                fingerprint = self._fingerprint(tool_name, arguments)
                if fingerprint == last_fingerprint:
                    repeated_count += 1
                else:
                    last_fingerprint = fingerprint
                    repeated_count = 1

                if repeated_count >= self.max_repeated_tool_calls:
                    state.tool_calls.append(
                        ToolCallRecord(
                            iteration=iteration,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments=arguments,
                            success=False,
                            error_code="repeated_tool_call",
                        )
                    )
                    return self._result(
                        state,
                        StopReason.REPEATED_TOOL_CALL,
                        message="检测到重复工具调用，Agent 已安全停止。",
                        error_code="repeated_tool_call",
                    )

                tool = self._get_tool(tool_name)
                if tool is None:
                    state.tool_calls.append(
                        ToolCallRecord(
                            iteration=iteration,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments=arguments,
                            success=False,
                            error_code="tool_not_found",
                        )
                    )
                    return self._result(
                        state,
                        StopReason.TOOL_ERROR,
                        message=f"请求的工具不可用：{tool_name}",
                        error_code="tool_not_found",
                    )

                self.audit_service.log_tool_call(tool_name, arguments)
                try:
                    observation, evidence, is_retrieval = self._execute_tool(
                        tool=tool,
                        tool_name=tool_name,
                        arguments=arguments,
                        query_plan=query_plan,
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.exception(
                        "[AGENT_TOOL_ERROR] trace_id=%s iteration=%s tool=%s error=%s",
                        trace_id,
                        iteration,
                        tool_name,
                        exc,
                    )
                    state.tool_calls.append(
                        ToolCallRecord(
                            iteration=iteration,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments=arguments,
                            success=False,
                            error_code=exc.__class__.__name__,
                        )
                    )
                    return self._result(
                        state,
                        StopReason.TOOL_ERROR,
                        message=(
                            "检索服务暂时不可用，请稍后重试。"
                            if tool_name == "search_documents"
                            else "工具执行失败，请稍后重试。"
                        ),
                        error_code=(
                            "retrieval_error"
                            if tool_name == "search_documents"
                            else exc.__class__.__name__
                        ),
                    )

                state.tool_calls.append(
                    ToolCallRecord(
                        iteration=iteration,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        success=True,
                    )
                )
                if is_retrieval:
                    state.retrieval_attempts += 1
                    state.evidence = self._merge_evidence(state.evidence, evidence)

                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": observation,
                    }
                )

                if is_retrieval and not evidence:
                    return self._result(
                        state,
                        StopReason.NO_RELEVANT_CONTEXT,
                        message="当前知识库没有足够信息回答该问题。",
                    )

        return self._result(
            state,
            StopReason.MAX_ITERATIONS,
            message="Agent 已达到最大迭代次数并安全停止。",
            error_code="max_iterations",
        )

    @staticmethod
    def _build_messages(
        query_plan: QueryPlan,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        system_content = (
            f"{SYSTEM_ROLE}\n\n"
            "你可以使用提供的工具获取回答所需的证据。"
            "工具返回后，基于观察结果给出最终答案；不要编造不存在的证据。\n\n"
            f"检索用独立查询：{query_plan.standalone_query}\n\n"
            f"回答约束：\n{ANSWER_RULES}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]
        for message in history:
            role = message.get("role")
            content = message.get("content")
            if role in {"system", "user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append(
            {
                "role": "user",
                "content": query_plan.original_query,
            }
        )
        return messages

    def _tool_schemas(self) -> list[dict[str, Any]]:
        if hasattr(self.registry, "to_openai_schemas"):
            return list(self.registry.to_openai_schemas())
        if hasattr(self.registry, "get_tool_schemas"):
            return list(self.registry.get_tool_schemas())
        return []

    def _get_tool(self, name: str) -> Any | None:
        if hasattr(self.registry, "get"):
            return self.registry.get(name)
        if hasattr(self.registry, "get_tool"):
            return self.registry.get_tool(name)
        return None

    @staticmethod
    def _parse_tool_call(raw_call: Any) -> tuple[str, str, dict[str, Any]]:
        if not isinstance(raw_call, dict):
            raise ValueError("tool call must be an object")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool call function must be an object")

        call_id = str(raw_call.get("id") or "")
        tool_name = function.get("name")
        if not call_id or not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool call id and function name are required")

        raw_arguments = function.get("arguments", {})
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise ValueError("tool arguments are not valid JSON") from exc
        elif isinstance(raw_arguments, dict):
            arguments = dict(raw_arguments)
        else:
            raise ValueError("tool arguments must be a JSON object")

        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must decode to an object")
        return call_id, tool_name, arguments

    @staticmethod
    def _apply_execution_constraints(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        query_plan: QueryPlan,
        mode: str,
        top_k: int,
    ) -> dict[str, Any]:
        constrained = dict(arguments)
        if tool_name == "search_documents":
            constrained["query"] = query_plan.standalone_query
            constrained["top_k"] = top_k
            constrained["mode"] = mode
            constrained["filters"] = dict(query_plan.filters)
        return constrained

    def _execute_tool(
        self,
        *,
        tool: Any,
        tool_name: str,
        arguments: dict[str, Any],
        query_plan: QueryPlan,
        trace_id: str,
    ) -> tuple[str, list[dict[str, Any]], bool]:
        if isinstance(tool, SearchTool) or tool_name == "search_documents":
            if hasattr(tool, "search"):
                results = tool.search(
                    query=query_plan.standalone_query,
                    top_k=arguments["top_k"],
                    mode=arguments["mode"],
                    filters=query_plan.filters or None,
                    min_score=settings.MIN_RETRIEVAL_SCORE,
                    trace_id=trace_id,
                )
                results = self._filter_search_results(results)
                return self._format_search_observation(results), list(results), True

        result = tool.execute(**arguments)
        evidence = self._extract_evidence(result)
        return self._stringify_result(result), evidence, False

    @staticmethod
    def _format_search_observation(results: list[dict[str, Any]]) -> str:
        if not results:
            return "No relevant documents found."
        blocks = []
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"[{index}] title: {item.get('title', '')}\n"
                f"doc_id: {item.get('doc_id', '')}\n"
                f"chunk_id: {item.get('chunk_id', '')}\n"
                f"content: {item.get('chunk_text', '')}\n"
                f"score: {float(item.get('score', 0.0)):.4f}"
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _filter_search_results(results: Any) -> list[dict[str, Any]]:
        """Re-apply the Agent-side quality gate at the Tool trust boundary."""
        if not isinstance(results, list):
            raise ValueError("search_documents must return a list")

        filtered: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                continue
            if score >= settings.MIN_RETRIEVAL_SCORE:
                filtered.append(item)
        return filtered

    @staticmethod
    def _extract_evidence(result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []
        for key in ("evidence", "results"):
            value = result.get(key)
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return list(value)
        return []

    @staticmethod
    def _stringify_result(result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    @staticmethod
    def _merge_evidence(
        current: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = list(current)
        seen = {
            str(item.get("chunk_id") or f"{item.get('doc_id')}:{item.get('chunk_index')}")
            for item in current
        }
        for item in new_items:
            key = str(
                item.get("chunk_id")
                or f"{item.get('doc_id')}:{item.get('chunk_index')}"
            )
            if key not in seen:
                merged.append(item)
                seen.add(key)
        return merged

    @staticmethod
    def _assistant_tool_call_message(
        response: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "role": response.get("role", "assistant"),
            "content": response.get("content"),
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"

    @staticmethod
    def _tool_call_id(raw_call: Any) -> str:
        return str(raw_call.get("id", "")) if isinstance(raw_call, dict) else ""

    @staticmethod
    def _tool_name(raw_call: Any) -> str:
        if not isinstance(raw_call, dict):
            return ""
        function = raw_call.get("function")
        return str(function.get("name", "")) if isinstance(function, dict) else ""

    @staticmethod
    def _result(
        state: AgentState,
        stop_reason: StopReason,
        *,
        answer: str = "",
        message: str = "",
        error_code: str = "",
    ) -> AgentRunResult:
        state.stop_reason = stop_reason
        logger.info(
            "[AGENT_STOP] trace_id=%s stop_reason=%s iterations=%s "
            "tool_calls=%s retrieval_attempts=%s error_code=%s",
            state.trace_id,
            stop_reason,
            state.iteration,
            len(state.tool_calls),
            state.retrieval_attempts,
            error_code or "-",
        )
        return AgentRunResult(
            stop_reason=stop_reason,
            answer=answer,
            message=message,
            iterations=state.iteration,
            retrieval_attempts=state.retrieval_attempts,
            tool_calls=state.tool_calls,
            evidence=state.evidence,
            messages=state.messages,
            error_code=error_code,
        )
