import json
import logging
from typing import Any

from agent.config.settings import settings
from agent.evidence.gate import EvidenceGate
from agent.llm.base import BaseLLM
from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE
from agent.retrieval.corrective import CorrectiveRetrievalPlanner
from agent.runtime.state import (
    AgentRunResult,
    AgentState,
    StopReason,
    ToolCallRecord,
)
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence
from agent.service.audit_service import AuditService
from agent.tools.executor import ToolExecutor
from toolset.tool_layer import SearchTool


logger = logging.getLogger("agent-layer")


class ToolExecutionFailure(RuntimeError):
    """Internal exception carrying a structured ToolExecutor failure."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class NoRelevantContext(RuntimeError):
    """Internal signal used when EvidenceGate rejects all retrieval attempts."""


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
        policy: IntentPolicy | None = None,
        tool_executor: ToolExecutor | None = None,
        evidence_gate: EvidenceGate | None = None,
        corrective_retrieval: CorrectiveRetrievalPlanner | None = None,
        history: list[dict[str, Any]] | None = None,
        trace_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        max_iterations: int | None = None,
        is_first_message: bool = False,
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

        if policy is not None and policy.max_iterations == 0:
            if query_plan.intent.value == "unsupported":
                return AgentRunResult(
                    stop_reason=StopReason.UNSUPPORTED,
                    message="当前请求超出 Agent 的能力范围。",
                    error_code="unsupported_intent",
                )
            return AgentRunResult(
                stop_reason=StopReason.POLICY_LIMIT,
                message="当前请求被执行策略安全拦截。",
                error_code="policy_limit",
            )

        limit = max_iterations if max_iterations is not None else self.max_iterations
        if policy is not None:
            limit = min(limit, policy.max_iterations)
        if limit < 1:
            raise ValueError("max_iterations must be at least 1")

        state = AgentState(
            trace_id=trace_id,
            query_plan=query_plan,
            messages=self._build_messages(query_plan, history or [], is_first_message=is_first_message),
        )
        schemas = self._tool_schemas(policy)
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
                if (
                    policy is not None
                    and policy.requires_citations
                    and not state.evidence
                    and schemas
                    and not answer
                ):
                    return self._result(
                        state,
                        StopReason.NO_RELEVANT_CONTEXT,
                        message="未检索到具体匹配的文档库片段，请尝试调整搜索关键词。",
                        error_code="evidence_required",
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
                if policy is not None and len(state.tool_calls) >= policy.max_tool_calls:
                    return self._result(
                        state,
                        StopReason.POLICY_LIMIT,
                        message="Agent 已达到当前意图的工具调用预算。",
                        error_code="max_tool_calls",
                    )

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
                    return self._fallback_final_answer(state, "检测到重复工具调用，Agent 已安全停止。")

                if policy is not None and tool_name not in policy.candidate_tools:
                    state.tool_calls.append(
                        ToolCallRecord(
                            iteration=iteration,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments=arguments,
                            success=False,
                            error_code="tool_not_allowed",
                        )
                    )
                    return self._result(
                        state,
                        StopReason.TOOL_ERROR,
                        message=f"当前意图不允许调用工具：{tool_name}",
                        error_code="tool_not_allowed",
                    )

                if (
                    policy is not None
                    and tool_name == "search_documents"
                    and state.retrieval_attempts >= policy.max_retrieval_attempts
                ):
                    return self._result(
                        state,
                        StopReason.POLICY_LIMIT,
                        message="Agent 已达到当前意图的检索预算。",
                        error_code="max_retrieval_attempts",
                    )

                tool = self._get_tool(tool_name, policy)
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
                        tool_call_id=call_id,
                        tool_executor=tool_executor,
                        retrieval_attempt=state.retrieval_attempts + 1,
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
                            error_code=(
                                exc.error_code
                                if isinstance(exc, ToolExecutionFailure)
                                else exc.__class__.__name__
                            ),
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
                            exc.error_code
                            if isinstance(exc, ToolExecutionFailure)
                            else (
                                "retrieval_error"
                                if tool_name == "search_documents"
                                else exc.__class__.__name__
                            )
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

                    try:
                        evidence, corrective_observations = self._apply_evidence_policy(
                            query_plan=query_plan,
                            policy=policy,
                            evidence_gate=evidence_gate,
                            corrective_retrieval=corrective_retrieval,
                            tool_executor=tool_executor,
                            trace_id=trace_id,
                            state=state,
                            previous_mode=mode,
                            previous_top_k=top_k,
                        )
                    except ToolExecutionFailure as exc:
                        return self._result(
                            state,
                            StopReason.TOOL_ERROR,
                            message=(
                                "检索服务暂时不可用。"
                                if tool_name == "search_documents"
                                else "工具执行失败，请稍后重试。"
                            ),
                            error_code=exc.error_code,
                        )
                    except NoRelevantContext as exc:
                        return self._result(
                            state,
                            StopReason.NO_RELEVANT_CONTEXT,
                            message=str(exc),
                        )

                    state.evidence = self._merge_evidence([], evidence)

                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": observation,
                    }
                )
                if is_retrieval:
                    for correction in corrective_observations:
                        state.messages.append(correction)

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
        is_first_message: bool = False,
    ) -> list[dict[str, Any]]:
        title_directive = (
            "\n\n【极重要指令】：这是本对话的第一个提问。请务必在最终回答的第一行输出您总结的对话标题，格式必须为：[TITLE: 3-10字精炼标题]，然后再换行输出正文回答。"
            if is_first_message
            else ""
        )
        system_content = (
            f"{SYSTEM_ROLE}\n\n"
            "你可以使用提供的工具获取回答所需的证据。"
            "工具返回后，基于观察结果给出最终答案；不要编造不存在的证据。\n\n"
            f"检索用独立查询：{query_plan.standalone_query}\n\n"
            f"回答约束：\n{ANSWER_RULES}"
            f"{title_directive}"
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

    def _tool_schemas(self, policy: IntentPolicy | None = None) -> list[dict[str, Any]]:
        if hasattr(self.registry, "to_openai_schemas"):
            schemas = list(self.registry.to_openai_schemas())
        elif hasattr(self.registry, "get_tool_schemas"):
            schemas = list(self.registry.get_tool_schemas())
        else:
            schemas = []

        if policy is None:
            return schemas
        allowed = set(policy.candidate_tools)
        return [
            schema
            for schema in schemas
            if isinstance(schema, dict)
            and isinstance(schema.get("function"), dict)
            and schema["function"].get("name") in allowed
        ]

    def _get_tool(
        self,
        name: str,
        policy: IntentPolicy | None = None,
    ) -> Any | None:
        if policy is not None and name not in policy.candidate_tools:
            return None
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

    def _fallback_final_answer(self, state: AgentState, default_message: str) -> AgentRunResult:
        """Fallback helper to attempt a tool-less final LLM answer generation when tool limits or repetitions occur."""
        try:
            fallback_messages = list(state.messages)
            fallback_messages.append({
                "role": "user",
                "content": "请结合已掌握的核心专业知识与背景信息，对用户提出的问题直接给出清晰、全面、有条理的回答，不要再调用任何工具。"
            })
            fallback_resp = self.llm.chat(fallback_messages, temperature=0.3)
            answer = fallback_resp.get("content", "").strip() if isinstance(fallback_resp, dict) else str(fallback_resp).strip()
            if answer:
                state.messages.append({"role": "assistant", "content": answer})
                return self._result(
                    state,
                    StopReason.FINAL_ANSWER,
                    answer=answer,
                )
        except Exception as exc:
            logger.warning("[Runner] Fallback final answer generation failed: %s", exc)

        return self._result(
            state,
            StopReason.REPEATED_TOOL_CALL,
            message=default_message,
            error_code="repeated_tool_call",
        )

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
            if not constrained.get("query"):
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
        tool_call_id: str,
        tool_executor: ToolExecutor | None = None,
        retrieval_attempt: int = 1,
    ) -> tuple[str, list[dict[str, Any]], bool]:
        if tool_executor is not None:
            result = tool_executor.execute(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                trace_id=trace_id,
                retrieval_attempt=retrieval_attempt,
            )
            if not result.success:
                raise ToolExecutionFailure(
                    result.error_code or "tool_execution_failed",
                    result.error_message or "工具执行失败，请稍后重试。",
                )
            evidence = [item.model_dump() for item in result.evidence]
            if tool_name == "search_documents":
                return self._format_search_observation(evidence), evidence, True
            return self._stringify_result(result.data or {}), evidence, False

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

    def _apply_evidence_policy(
        self,
        *,
        query_plan: QueryPlan,
        policy: IntentPolicy | None,
        evidence_gate: EvidenceGate | None,
        corrective_retrieval: CorrectiveRetrievalPlanner | None,
        tool_executor: ToolExecutor | None,
        trace_id: str,
        state: AgentState,
        previous_mode: str,
        previous_top_k: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Gate retrieval evidence and perform at most one corrective pass."""

        current = self._typed_evidence(state.evidence)
        if policy is None or evidence_gate is None:
            return state.evidence or [], []

        gate_result = evidence_gate.evaluate(
            query_plan,
            policy,
            current,
            retrieval_attempt=state.retrieval_attempts,
        )
        if gate_result.accepted:
            return [item.model_dump() for item in gate_result.evidence], []

        if (
            not gate_result.should_retry
            or corrective_retrieval is None
            or tool_executor is None
        ):
            return [], []

        requests = corrective_retrieval.plan(
            query_plan,
            policy,
            gate_result,
            previous_mode=previous_mode,
            previous_top_k=previous_top_k,
        )
        if not requests:
            return [], []

        correction_messages: list[dict[str, Any]] = []
        corrected = list(current)
        for index, request in enumerate(requests, start=1):
            call_id = f"corrective-{state.tool_calls[-1].tool_call_id}-{index}"
            arguments = {
                "query": request.query,
                "top_k": request.top_k,
                "mode": request.mode,
                "filters": request.filters,
            }
            result = tool_executor.execute(
                tool_call_id=call_id,
                tool_name="search_documents",
                arguments=arguments,
                trace_id=trace_id,
                retrieval_attempt=request.retrieval_attempt,
            )
            if not result.success:
                raise ToolExecutionFailure(
                    result.error_code or "tool_execution_failed",
                    result.error_message or "纠偏检索失败。",
                )
            state.retrieval_attempts = max(
                state.retrieval_attempts,
                request.retrieval_attempt,
            )
            corrected.extend(result.evidence)
            correction_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": "search_documents",
                    "content": self._format_search_observation(
                        [item.model_dump() for item in result.evidence]
                    ),
                }
            )

        second_gate = evidence_gate.evaluate(
            query_plan,
            policy,
            corrected,
            retrieval_attempt=state.retrieval_attempts,
        )
        if not second_gate.accepted:
            return [], correction_messages
        return [item.model_dump() for item in second_gate.evidence], correction_messages

    @staticmethod
    def _typed_evidence(items: list[dict[str, Any]]) -> list[Evidence]:
        typed: list[Evidence] = []
        for item in items:
            try:
                typed.append(Evidence.model_validate(item))
            except (TypeError, ValueError):
                continue
        return typed

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
                f"content: {item.get('chunk_text', item.get('content', ''))}\n"
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
