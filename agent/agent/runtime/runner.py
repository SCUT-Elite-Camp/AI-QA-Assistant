import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from agent.answer import AnswerCompletenessChecker
from agent.answer.generator import AnswerGenerator, AnswerModelPreference
from agent.config.settings import settings
from agent.evidence import EvidenceGate, WikiEvidenceSupplementer
from agent.exploration.controller import ExplorationController
from agent.llm.base import BaseLLM
from agent.retrieval.corrective import CorrectiveRetrievalPlanner
from agent.runtime.support import RuntimeSupport
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

    _MAX_PARALLEL_SUB_QUERIES = 4
    _WIKI_TOOLS = {
        "wiki_search",
        "wiki_read_page",
        "wiki_read_sources",
        "wiki_search_evidence",
    }
    _DIRECT_ROUTE_TOOLS = {
        "search_documents",
        "find_documents",
        "get_document",
        "search_library",
        "search_attachments",
        "inspect_attachment",
    }

    def __init__(
        self,
        llm: BaseLLM,
        registry: Any,
        audit_service: AuditService,
        max_iterations: int | None = None,
        max_repeated_tool_calls: int | None = None,
        answer_completeness_checker: AnswerCompletenessChecker | None = None,
        answer_llm: BaseLLM | None = None,
        fast_answer_llm: BaseLLM | None = None,
        answer_generator: AnswerGenerator | None = None,
        exploration_controller: ExplorationController | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.audit_service = audit_service
        self.answer_completeness_checker = answer_completeness_checker
        self.runtime_support = RuntimeSupport(answer_completeness_checker)
        self.answer_llm = answer_llm or llm
        self.fast_answer_llm = fast_answer_llm
        self.answer_generator = answer_generator or AnswerGenerator(
            complex_llm=self.answer_llm,
            fast_llm=self.fast_answer_llm,
        )
        self.exploration_controller = exploration_controller or ExplorationController()
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
        soul_content: str | None = None,
        exploration_mode: str = "auto",
        navigation_scopes: tuple[str, ...] = (),
        answer_model_preference: AnswerModelPreference = "auto",
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
            answer_model_preference=answer_model_preference,
            messages=self._build_messages(
                query_plan,
                history or [],
                is_first_message=is_first_message,
                soul_content=soul_content,
                policy=policy,
            ),
        )
        schemas = self._tool_schemas(policy)
        navigation_enabled = (
            settings.AGENTIC_EXPLORATION_ENABLED
            and exploration_mode != "off"
            and policy is not None
            and tool_executor is not None
            and any(
                schema.get("function", {}).get("name") == "wiki_search"
                for schema in schemas
                if isinstance(schema, dict)
            )
        )
        last_fingerprint: str | None = None
        repeated_count = 0
        next_wiki_tool: str | None = None
        wiki_route_active = False
        retrieval_route: str | None = None

        for iteration in range(1, limit + 1):
            state.iteration = iteration
            self.audit_service.log_step(iteration - 1, query_plan.original_query)

            try:
                # Once retrieval evidence has passed the evidence policy, the
                # next model turn is answer generation. Hiding tool schemas at
                # that point prevents providers from requesting the identical
                # search again instead of consuming the observation.
                available_tools = schemas if not state.evidence else None
                if available_tools and retrieval_route is None:
                    available_tools = self._route_entry_schemas(
                        available_tools,
                    )
                if next_wiki_tool:
                    available_tools = [
                        schema for schema in schemas
                        if schema.get("function", {}).get("name") == next_wiki_tool
                    ]
                if state.evidence and not next_wiki_tool:
                    # Start answer generation from a clean evidence-only prompt.
                    # Replaying the prior assistant tool call can make some
                    # providers request the same tool again even when schemas
                    # are hidden, which then costs a second answer-model call.
                    response = self._generate_from_clean_evidence_context(state)
                elif available_tools:
                    response = self.llm.chat(state.messages, tools=available_tools)
                else:
                    response = self._chat_for_answer(state, state.messages)
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

            if state.evidence and tool_calls and not next_wiki_tool:
                logger.warning(
                    "[POST_EVIDENCE_TOOL_CALL_IGNORED] trace_id=%s iteration=%s calls=%s",
                    trace_id,
                    iteration,
                    len(tool_calls),
                )
                if isinstance(content, str) and content.strip():
                    tool_calls = []
                else:
                    try:
                        response = self._generate_from_clean_evidence_context(state)
                    except Exception as exc:
                        logger.exception(
                            "[FORCED_ANSWER_ERROR] trace_id=%s iteration=%s error=%s",
                            trace_id,
                            iteration,
                            exc,
                        )
                        return self._result(
                            state,
                            StopReason.LLM_ERROR,
                            message="The model could not generate a final answer from the accepted evidence.",
                            error_code=exc.__class__.__name__,
                        )
                    content = response.get("content")
                    tool_calls = []

            if not tool_calls:
                answer = content.strip() if isinstance(content, str) else ""
                if not answer:
                    return self._result(
                        state,
                        StopReason.LLM_ERROR,
                        message="模型服务暂时不可用，请稍后重试。",
                        error_code="empty_llm_response",
                    )
                if next_wiki_tool:
                    state.messages.append({
                        "role": "system",
                        "content": (
                            "Wiki navigation has a pending source step: call "
                            f"{next_wiki_tool} before answering."
                        ),
                    })
                    continue
                if (
                    policy is not None
                    and policy.requires_citations
                    and not state.evidence
                    and schemas
                ):
                    if retrieval_route is None and iteration < limit:
                        state.messages.append({
                            "role": "system",
                            "content": self._route_required_message(
                                navigation_enabled=navigation_enabled,
                            ),
                        })
                        logger.warning(
                            "[RETRIEVAL_ROUTE_REQUIRED] trace_id=%s iteration=%s",
                            trace_id,
                            iteration,
                        )
                        continue
                    return self._result(
                        state,
                        StopReason.NO_RELEVANT_CONTEXT,
                        message="Agent 未完成必需的检索路由选择。",
                        error_code="retrieval_route_required",
                    )
                answer = self._check_and_repair_answer(
                    state=state,
                    policy=policy,
                    answer=answer,
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

            pending_calls = list(tool_calls)
            while pending_calls:
                raw_call = pending_calls.pop(0)
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
                        navigation_scopes=navigation_scopes,
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

                if next_wiki_tool and tool_name != next_wiki_tool:
                    state.tool_calls.append(ToolCallRecord(
                        iteration=iteration,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        success=False,
                        error_code="navigation_step_out_of_order",
                    ))
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": f"Complete the pending Wiki step with {next_wiki_tool}.",
                    })
                    continue

                exploration_tools = self._WIKI_TOOLS
                if (
                    navigation_enabled
                    and not wiki_route_active
                    and tool_name in exploration_tools
                ):
                    state.tool_calls.append(ToolCallRecord(
                        iteration=iteration,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        success=False,
                        error_code="wiki_route_must_start_with_search",
                    ))
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": (
                            "Wiki retrieval is started by the coverage controller "
                            "after accepted Direct evidence. Continue with Direct retrieval."
                        ),
                    })
                    continue
                if retrieval_route == "direct_only" and tool_name in exploration_tools:
                    state.tool_calls.append(ToolCallRecord(
                        iteration=iteration,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        success=False,
                        error_code="retrieval_route_locked",
                    ))
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": "The current request is locked to Direct retrieval.",
                    })
                    continue
                if (
                    tool_name in exploration_tools
                    and state.exploration_rounds >= settings.EXPLORATION_MAX_ROUNDS
                ):
                    return self._fallback_final_answer(
                        state, "Agent 已达到探索轮次预算。",
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
                    if tool_name in exploration_tools:
                        state.messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tool_name,
                            "content": (
                                "Duplicate Wiki navigation call suppressed; continue "
                                "with the next source-resolution step."
                            ),
                        })
                        continue
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
                    navigation_enabled
                    and retrieval_route is None
                    and tool_name in self._DIRECT_ROUTE_TOOLS
                ):
                    retrieval_route = "direct_pending_coverage"
                    logger.info(
                        "[RETRIEVAL_ROUTE] trace_id=%s route=%s selected_tool=%s",
                        trace_id,
                        retrieval_route,
                        tool_name,
                    )

                is_retrieval_tool = tool_name in {
                    "search_documents",
                    "find_documents",
                    "get_document",
                    "search_library",
                    "search_attachments",
                    "inspect_attachment",
                    "wiki_search_evidence",
                }
                if (
                    policy is not None
                    and is_retrieval_tool
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
                    if (
                        tool_name == "search_documents"
                        and tool_executor is not None
                        and state.retrieval_attempts == 0
                        and query_plan.intent.value == "comparison"
                        and len(query_plan.sub_queries) >= 2
                    ):
                        observation, evidence, is_retrieval = (
                            self._execute_parallel_comparison_retrieval(
                                query_plan=query_plan,
                                arguments=arguments,
                                trace_id=trace_id,
                                tool_call_id=call_id,
                                tool_executor=tool_executor,
                                retrieval_attempt=1,
                            )
                        )
                    else:
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
                        if (
                            tool_name == "search_documents"
                            and query_plan.intent.value == "summarization"
                            and tool_executor is not None
                            and evidence
                            and policy is not None
                            and "get_document" in policy.candidate_tools
                        ):
                            target_doc_id = evidence[0].get("doc_id") or evidence[0].get("document_id")
                            if target_doc_id:
                                try:
                                    doc_result = tool_executor.execute(
                                        tool_call_id=f"{call_id}-full-doc",
                                        tool_name="get_document",
                                        arguments={"doc_id": target_doc_id},
                                        trace_id=trace_id,
                                        retrieval_attempt=state.retrieval_attempts + 1,
                                    )
                                    if doc_result.success and doc_result.evidence:
                                        evidence = [item.model_dump() for item in doc_result.evidence]
                                        observation = self._format_search_observation(evidence)
                                except Exception as doc_exc:
                                    logger.warning("[Runner] Auto full-document retrieval failed: %s", doc_exc)
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
                if tool_name in exploration_tools:
                    state.exploration_rounds += 1
                    next_wiki_tool = self._next_wiki_tool(tool_name, observation)
                corrective_observations: list[dict[str, Any]] = []
                if is_retrieval:
                    state.retrieval_attempts += 1
                    if tool_name == "wiki_search_evidence":
                        self._supplement_wiki_evidence(
                            state,
                            evidence=evidence,
                            evidence_gate=evidence_gate,
                        )
                    else:
                        state.evidence = self._merge_evidence(state.evidence, evidence)
                    if navigation_enabled and tool_name != "wiki_search_evidence":
                        state.evidence = state.evidence[:settings.EXPLORATION_MAX_EVIDENCE]

                    try:
                        (
                            evidence,
                            corrective_observations,
                            tool_budget_exhausted,
                        ) = self._apply_evidence_policy(
                            query_plan=query_plan,
                            policy=policy,
                            evidence_gate=evidence_gate,
                            corrective_retrieval=corrective_retrieval,
                            tool_executor=tool_executor,
                            trace_id=trace_id,
                            state=state,
                            previous_mode=mode,
                            previous_top_k=top_k,
                            preserve_evidence_order=(
                                tool_name == "wiki_search_evidence"
                                and settings.WIKI_CONTEXT_TOP_K > 0
                            ),
                        )
                        if tool_budget_exhausted:
                            return self._result(
                                state,
                                StopReason.POLICY_LIMIT,
                                message="Agent 已达到当前意图的工具调用预算。",
                                error_code="max_tool_calls",
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
                        state.evidence = []
                        return self._result(
                            state,
                            StopReason.NO_RELEVANT_CONTEXT,
                            message=str(exc),
                            error_code="evidence_insufficient_after_correction",
                        )

                    state.evidence = list(evidence)
                    if (
                        navigation_enabled
                        and retrieval_route == "direct_pending_coverage"
                        and tool_name in self._DIRECT_ROUTE_TOOLS
                    ):
                        assessment = self.exploration_controller.assess_after_direct(
                            query_plan,
                            self._typed_evidence(state.evidence),
                            exploration_mode=exploration_mode,
                            wiki_available=any(
                                schema.get("function", {}).get("name") == "wiki_search"
                                for schema in schemas
                                if isinstance(schema, dict)
                            ),
                        )
                        state.coverage_assessments.append(assessment)
                        if assessment.should_explore:
                            retrieval_route = "direct_plus_wiki"
                            wiki_route_active = True
                            next_wiki_tool = "wiki_search"
                            wiki_call = self._controller_wiki_search_call(query_plan)
                            pending_calls.append(wiki_call)
                            # Keep the controller-started call in the same
                            # assistant/tool exchange for provider-safe history.
                            state.messages[-1]["tool_calls"].append(wiki_call)
                        else:
                            retrieval_route = "direct_only"
                        logger.info(
                            "[EXPLORATION_DECISION] trace_id=%s route=%s reason=%s "
                            "missing=%s evidence=%s",
                            trace_id,
                            retrieval_route,
                            assessment.reason,
                            assessment.missing_facets,
                            assessment.unique_evidence,
                        )
                    if tool_name == "wiki_search_evidence":
                        observation = self._format_search_observation(state.evidence)
                elif tool_name in exploration_tools and next_wiki_tool is None:
                    # Wiki navigation can legitimately find no page/source. In
                    # that case the Direct prefetch remains usable, but it must
                    # pass the same EvidenceGate before answer generation.
                    try:
                        (
                            evidence,
                            corrective_observations,
                            tool_budget_exhausted,
                        ) = self._apply_evidence_policy(
                            query_plan=query_plan,
                            policy=policy,
                            evidence_gate=evidence_gate,
                            corrective_retrieval=corrective_retrieval,
                            tool_executor=tool_executor,
                            trace_id=trace_id,
                            state=state,
                            previous_mode=mode,
                            previous_top_k=top_k,
                            preserve_evidence_order=False,
                        )
                        if tool_budget_exhausted:
                            return self._result(
                                state,
                                StopReason.POLICY_LIMIT,
                                message="Agent 已达到当前意图的工具调用预算。",
                                error_code="max_tool_calls",
                            )
                    except ToolExecutionFailure as exc:
                        return self._result(
                            state,
                            StopReason.TOOL_ERROR,
                            message="检索服务暂时不可用。",
                            error_code=exc.error_code,
                        )
                    except NoRelevantContext as exc:
                        state.evidence = []
                        return self._result(
                            state,
                            StopReason.NO_RELEVANT_CONTEXT,
                            message=str(exc),
                            error_code="evidence_insufficient_after_correction",
                        )
                    state.evidence = list(evidence)

                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": observation,
                    }
                )
                if (is_retrieval or tool_name in exploration_tools) and not next_wiki_tool:
                    for correction in corrective_observations:
                        state.messages.append(correction)
                    # One retrieval batch may already cover every planned
                    # comparison target. Ignore additional search calls from
                    # the same model response and move to answer generation.
                    break

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
        soul_content: str | None = None,
        policy: IntentPolicy | None = None,
    ) -> list[dict[str, Any]]:
        return RuntimeSupport.build_messages(
            query_plan,
            history,
            is_first_message=is_first_message,
            soul_content=soul_content,
            policy=policy,
        )

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

    @classmethod
    def _route_entry_schemas(
        cls,
        schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Establish and gate Direct evidence before ExplorationController can
        # start the bounded Wiki route.
        allowed = cls._DIRECT_ROUTE_TOOLS
        return [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
        ]

    @staticmethod
    def _controller_wiki_search_call(query_plan: QueryPlan) -> dict[str, Any]:
        return {
            "id": "controller-wiki-route",
            "type": "function",
            "function": {
                "name": "wiki_search",
                "arguments": json.dumps(
                    {"query": query_plan.standalone_query},
                    ensure_ascii=False,
                ),
                },
        }

    @staticmethod
    def _route_required_message(*, navigation_enabled: bool) -> str:
        if navigation_enabled:
            return (
                "This request requires cited Evidence. Retrieve Direct evidence "
                "before answering; the server will start Wiki exploration only "
                "when its coverage assessment finds a gap."
            )
        return (
            "This request requires cited Evidence. Call an available Direct "
            "retrieval tool before answering."
        )

    @staticmethod
    def _document_tool_guidance(policy: IntentPolicy | None) -> str:
        return RuntimeSupport.document_tool_guidance(policy)

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
        navigation_scopes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        constrained = dict(arguments)
        if tool_name == "search_documents":
            constrained["query"] = query_plan.standalone_query
            constrained["top_k"] = top_k
            constrained["mode"] = mode
            constrained["filters"] = dict(query_plan.filters)
        elif tool_name == "search_library":
            constrained["query"] = query_plan.standalone_query
            constrained["top_k"] = top_k
            constrained["mode"] = mode
            doc_ids = query_plan.filters.get("doc_ids")
            if doc_ids is None and query_plan.filters.get("doc_id") is not None:
                doc_ids = [query_plan.filters["doc_id"]]
            if doc_ids is not None:
                constrained["doc_ids"] = (
                    [doc_ids] if isinstance(doc_ids, str) else list(doc_ids)
                )
        elif tool_name == "search_attachments":
            constrained["query"] = query_plan.standalone_query
            constrained["top_k"] = top_k
        elif tool_name == "inspect_attachment":
            constrained["question"] = str(
                constrained.get("question") or query_plan.standalone_query
            )
        elif tool_name == "find_documents":
            if not constrained.get("query") and not constrained.get("filters"):
                constrained["query"] = query_plan.standalone_query
            constrained["top_k"] = top_k
            constrained["filters"] = dict(query_plan.filters)
        elif tool_name == "get_document":
            doc_id = str(constrained.get("doc_id") or "")
            if doc_id and not AgentRunner._document_is_allowed(
                doc_id,
                query_plan.filters,
            ):
                raise ValueError("document_not_allowed")
        elif tool_name in {
            "wiki_search", "wiki_read_page", "wiki_read_sources",
            "wiki_search_evidence",
        }:
            if not navigation_scopes:
                raise ValueError("navigation source scope is not authorized")
            requested = str(constrained.get("source_scope") or "")
            if requested not in navigation_scopes:
                constrained["source_scope"] = navigation_scopes[0]
            if tool_name == "wiki_search":
                constrained["query"] = query_plan.standalone_query
                constrained["top_k"] = min(
                    12, max(top_k, int(constrained.get("top_k") or top_k))
                )
            elif tool_name == "wiki_search_evidence":
                constrained["query"] = query_plan.standalone_query
                constrained["top_k"] = min(
                    20, max(top_k, int(constrained.get("top_k") or top_k))
                )
                constrained["mode"] = mode
        return constrained

    @staticmethod
    def _document_is_allowed(doc_id: str, filters: dict[str, Any]) -> bool:
        constraints: list[set[str]] = []
        for key in ("doc_id", "doc_ids"):
            if key not in filters:
                continue
            value = filters[key]
            if isinstance(value, str):
                constraints.append({value})
            elif isinstance(value, (list, tuple, set)):
                constraints.append({str(item) for item in value})
            else:
                return False
        return all(doc_id in allowed for allowed in constraints)

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
            if tool_name in {
                "search_documents",
                "search_library",
                "search_attachments",
                "inspect_attachment",
                "wiki_search_evidence",
            }:
                return self._format_search_observation(evidence), evidence, True
            if tool_name == "find_documents" and query_plan.intent.value != "document_search":
                return self._stringify_result(result.data or {}), [], False
            is_retrieval = tool_name in {
                "find_documents",
                "get_document",
                "search_library",
                "search_attachments",
                "inspect_attachment",
                "wiki_search_evidence",
            }
            return self._stringify_result(result.data or {}), evidence, is_retrieval

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
        return (
            self._stringify_result(result),
            evidence,
            tool_name in {
                "find_documents",
                "get_document",
                "search_library",
                "search_attachments",
                "inspect_attachment",
                "wiki_search_evidence",
            },
        )

    def _execute_parallel_comparison_retrieval(
        self,
        *,
        query_plan: QueryPlan,
        arguments: dict[str, Any],
        trace_id: str,
        tool_call_id: str,
        tool_executor: ToolExecutor,
        retrieval_attempt: int,
    ) -> tuple[str, list[dict[str, Any]], bool]:
        """Retrieve independent comparison targets in one bounded round.

        A partial failure is represented as missing evidence for that target so
        the deterministic EvidenceGate can request one targeted corrective pass.
        The whole round fails only when every target execution fails.
        """

        queries = list(
            dict.fromkeys(
                query.strip()
                for query in query_plan.sub_queries
                if query.strip()
            )
        )[: self._MAX_PARALLEL_SUB_QUERIES]
        if len(queries) < 2:
            raise ValueError("parallel comparison retrieval requires two targets")

        def execute(index: int, query: str):
            child_arguments = dict(arguments)
            child_arguments["query"] = query
            return query, tool_executor.execute(
                tool_call_id=f"{tool_call_id}-sub-{index}",
                tool_name="search_documents",
                arguments=child_arguments,
                trace_id=trace_id,
                retrieval_attempt=retrieval_attempt,
            )

        results = []
        with ThreadPoolExecutor(
            max_workers=len(queries),
            thread_name_prefix="comparison-retrieval",
        ) as pool:
            futures = {
                pool.submit(execute, index, query): (index, query)
                for index, query in enumerate(queries, start=1)
            }
            for future in as_completed(futures):
                results.append(future.result())

        successful = [result for _, result in results if result.success]
        if not successful:
            first_failure = results[0][1]
            raise ToolExecutionFailure(
                first_failure.error_code or "retrieval_error",
                first_failure.error_message or "All comparison retrievals failed.",
            )

        evidence = [
            item.model_dump()
            for result in successful
            for item in result.evidence
        ]
        failed_queries = [query for query, result in results if not result.success]
        logger.info(
            "[PARALLEL_COMPARISON_RETRIEVAL] trace_id=%s targets=%s "
            "successful=%s failed=%s attempt=%s",
            trace_id,
            queries,
            len(successful),
            failed_queries,
            retrieval_attempt,
        )
        return self._format_search_observation(evidence), evidence, True

    def _generate_from_clean_evidence_context(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """Generate an answer without carrying tool-call history forward."""

        context_history = self._history_before_current_query(state)
        clean_messages, ordered_evidence = self.answer_generator.build_evidence_messages(
            state.query_plan,
            state.evidence,
            context_history,
            preserve_evidence_order=bool(state.wiki_evidence_supplements),
        )
        state.evidence = ordered_evidence
        response = self._chat_for_answer(
            state,
            clean_messages,
        )
        if not isinstance(response, dict):
            raise ValueError("forced answer response must be an object")
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("forced answer response must contain text")
        return response

    @staticmethod
    def _history_before_current_query(state: AgentState) -> list[dict[str, Any]]:
        """Keep initial Memory/legacy history when the final answer uses clean evidence."""
        current_index: int | None = None
        for index in range(len(state.messages) - 1, -1, -1):
            message = state.messages[index]
            if (
                message.get("role") == "user"
                and message.get("content") == state.query_plan.original_query
            ):
                current_index = index
                break

        if current_index is None:
            return []

        return [
            {"role": message["role"], "content": message["content"]}
            for message in state.messages[1:current_index]
            if message.get("role") in {"system", "user", "assistant"}
            and isinstance(message.get("content"), str)
        ]

    @staticmethod
    def _prioritize_evidence_for_answer(
        query: str,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prefer directly named technical documents without dropping evidence."""

        return AnswerGenerator._prioritize_evidence(query, evidence)

    def _chat_for_answer(
        self,
        state: AgentState,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.answer_generator.chat(
            messages,
            query_plan=state.query_plan,
            retrieval_attempts=state.retrieval_attempts,
            trace_id=state.trace_id,
            preference=state.answer_model_preference,  # type: ignore[arg-type]
        )

    def _select_answer_llm(self, state: AgentState) -> BaseLLM:
        from agent.answer.complexity import answer_complexity_reasons

        if self.fast_answer_llm is None or answer_complexity_reasons(
            state.query_plan,
            retrieval_attempts=state.retrieval_attempts,
        ):
            return self.answer_llm
        return self.fast_answer_llm

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
        preserve_evidence_order: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        """Gate retrieval evidence and perform at most one corrective pass."""

        current = self._typed_evidence(state.evidence)
        if policy is None or evidence_gate is None:
            if not state.evidence:
                raise NoRelevantContext("No relevant context passed the Agent evidence threshold.")
            return state.evidence or [], [], False

        gate_result = evidence_gate.evaluate(
            query_plan,
            policy,
            current,
            retrieval_attempt=state.retrieval_attempts,
        )
        self.runtime_support.record_evidence_gate(state, gate_result)
        if gate_result.accepted:
            return self._accepted_evidence(
                current,
                gate_result.evidence,
                preserve_order=preserve_evidence_order,
            ), [], False

        if (
            not gate_result.should_retry
            or gate_result.retrieval_attempt != 1
            or corrective_retrieval is None
            or tool_executor is None
        ):
            raise NoRelevantContext(self._insufficient_evidence_message(gate_result))

        requests = corrective_retrieval.plan(
            query_plan,
            policy,
            gate_result,
            previous_mode=previous_mode,
            previous_top_k=previous_top_k,
        )
        if not requests:
            return [], [], False

        correction_messages: list[dict[str, Any]] = []
        corrected = list(current)
        base_call_id = state.tool_calls[-1].tool_call_id
        direct_corrected: list[Evidence] = []
        if preserve_evidence_order:
            supplement_keys = {
                evidence_gate.evidence_key(item)
                for item in self._typed_evidence(state.wiki_evidence_supplements)
            }
            direct_corrected = [
                item for item in current
                if evidence_gate.evidence_key(item) not in supplement_keys
            ]
        for index, request in enumerate(requests, start=1):
            if len(state.tool_calls) >= policy.max_tool_calls:
                return [], [], True
            call_id = f"corrective-{base_call_id}-{index}"
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
            state.tool_calls.append(
                ToolCallRecord(
                    iteration=state.iteration,
                    tool_call_id=call_id,
                    tool_name="search_documents",
                    arguments=arguments,
                    success=result.success,
                    error_code=result.error_code,
                )
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
            if preserve_evidence_order:
                direct_by_key = {
                    evidence_gate.evidence_key(item): item
                    for item in direct_corrected
                }
                for item in result.evidence:
                    direct_by_key[evidence_gate.evidence_key(item)] = item
                direct_corrected = list(direct_by_key.values())
                state.evidence = [
                    item.model_dump() for item in direct_corrected
                ]
                self._supplement_wiki_evidence(
                    state,
                    evidence=[],
                    evidence_gate=evidence_gate,
                )
                corrected = self._typed_evidence(state.evidence)
            else:
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
        self.runtime_support.record_evidence_gate(state, second_gate)
        if not second_gate.accepted:
            raise NoRelevantContext(self._insufficient_evidence_message(second_gate))
        return self._accepted_evidence(
            corrected,
            second_gate.evidence,
            preserve_order=preserve_evidence_order,
        ), correction_messages, False

    @staticmethod
    def _accepted_evidence(
        original: list[Evidence],
        accepted: list[Evidence],
        *,
        preserve_order: bool,
    ) -> list[dict[str, Any]]:
        if not preserve_order:
            return [item.model_dump() for item in accepted]
        accepted_keys = {EvidenceGate.evidence_key(item) for item in accepted}
        return [
            item.model_dump()
            for item in original
            if EvidenceGate.evidence_key(item) in accepted_keys
        ]

    @staticmethod
    def _insufficient_evidence_message(gate_result) -> str:
        return RuntimeSupport.insufficient_evidence_message(gate_result)

    @staticmethod
    def _next_wiki_tool(tool_name: str, observation: str) -> str | None:
        if tool_name == "wiki_search_evidence":
            return None
        try:
            payload = json.loads(observation)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if tool_name == "wiki_search" and payload.get("pages"):
            return "wiki_read_page"
        if tool_name == "wiki_read_page" and payload.get("page"):
            return "wiki_read_sources"
        if tool_name == "wiki_read_sources" and payload.get("sources"):
            return "wiki_search_evidence"
        return None

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
    def _supplement_wiki_evidence(
        state: AgentState,
        *,
        evidence: list[dict[str, Any]],
        evidence_gate: EvidenceGate | None,
    ) -> None:
        if settings.WIKI_CONTEXT_TOP_K == 0:
            state.evidence = AgentRunner._merge_evidence(state.evidence, evidence)
            return

        gate = evidence_gate or EvidenceGate()
        state.wiki_evidence_candidates.extend(evidence)
        previous_supplement_keys = {
            gate.evidence_key(item)
            for item in AgentRunner._typed_evidence(
                state.wiki_evidence_supplements
            )
        }
        direct = [
            item
            for item in AgentRunner._typed_evidence(state.evidence)
            if gate.evidence_key(item) not in previous_supplement_keys
        ]
        result = WikiEvidenceSupplementer(
            evidence_gate=gate,
            wiki_top_k=settings.WIKI_CONTEXT_TOP_K,
        ).supplement(
            direct,
            AgentRunner._typed_evidence(state.wiki_evidence_candidates),
        )
        state.evidence = [item.model_dump() for item in result.evidence]
        state.wiki_evidence_supplements = [
            item.model_dump() for item in result.evidence[len(direct):]
        ]
        logger.info(
            "[WIKI_EVIDENCE_SUPPLEMENT] trace_id=%s direct_retained=%s "
            "wiki_candidates=%s wiki_selected=%s "
            "wiki_duplicates_skipped=%s total=%s",
            state.trace_id,
            len(direct),
            len(state.wiki_evidence_candidates),
            result.wiki_selected,
            result.wiki_duplicates_skipped,
            len(result.evidence),
        )

    @staticmethod
    def _merge_evidence(
        current: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = list(current)
        seen = {AgentRunner._evidence_dict_key(item) for item in current}
        for item in new_items:
            key = AgentRunner._evidence_dict_key(item)
            if key not in seen:
                merged.append(item)
                seen.add(key)
        return merged

    @staticmethod
    def _evidence_dict_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(item.get("source_scope") or "").strip(),
            str(item.get("document_id") or item.get("doc_id") or "").strip(),
            str(item.get("version_id") or "").strip(),
            str(
                item.get("chunk_id")
                or f"{item.get('doc_id')}:{item.get('chunk_index')}"
            ).strip(),
        )

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
        return RuntimeSupport.result(
            state,
            stop_reason,
            answer=answer,
            message=message,
            error_code=error_code,
        )

    def _check_and_repair_answer(
        self,
        *,
        state: AgentState,
        policy: IntentPolicy | None,
        answer: str,
    ) -> str:
        return self.runtime_support.check_and_repair_answer(
            state=state,
            policy=policy,
            answer=answer,
        )
