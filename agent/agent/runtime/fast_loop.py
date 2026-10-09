"""Deterministic, bounded execution for simple chat and enterprise QA turns."""

import logging
from typing import Any

from agent.answer.generator import AnswerGenerator
from agent.evidence import EvidenceGate
from agent.retrieval.corrective import CorrectiveRetrievalPlanner
from agent.runtime.support import RuntimeSupport
from agent.runtime.state import AgentRunResult, AgentState, StopReason, ToolCallRecord
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.tools.executor import ToolExecutor

logger = logging.getLogger("agent-layer")


class FastLoop:
    """Skip model tool selection; retrieve deterministically and answer once."""

    def __init__(
        self,
        *,
        answer_generator: AnswerGenerator,
        runtime_support: RuntimeSupport,
    ) -> None:
        self.answer_generator = answer_generator
        self.runtime_support = runtime_support

    def run(
        self,
        query_plan: QueryPlan,
        *,
        policy: IntentPolicy,
        tool_executor: ToolExecutor,
        evidence_gate: EvidenceGate,
        corrective_retrieval: CorrectiveRetrievalPlanner,
        history: list[dict[str, Any]],
        trace_id: str,
        mode: str,
        top_k: int,
        is_first_message: bool = False,
        soul_content: str | None = None,
    ) -> AgentRunResult:
        state = AgentState(
            trace_id=trace_id,
            query_plan=query_plan,
            answer_model_preference="fast",
            messages=self.runtime_support.build_messages(
                query_plan,
                history,
                is_first_message=is_first_message,
                soul_content=soul_content,
                policy=policy,
            ),
        )
        if query_plan.needs_clarification:
            return self.runtime_support.result(
                state,
                StopReason.CLARIFICATION_REQUIRED,
                message=query_plan.clarification_question,
            )
        if policy.max_iterations == 0:
            return self.runtime_support.result(
                state,
                StopReason.UNSUPPORTED,
                message="当前请求超出 Agent 的能力范围。",
                error_code="unsupported_intent",
            )

        if policy.retrieval_strategy == "none":
            return self._answer(state, policy, state.messages, preference="fast")

        if len(state.tool_calls) >= policy.max_tool_calls:
            return self.runtime_support.result(
                state,
                StopReason.POLICY_LIMIT,
                message="Agent 已达到当前意图的工具调用预算。",
                error_code="max_tool_calls",
            )

        call_id = f"fast-direct-{trace_id}"
        arguments = {
            "query": query_plan.standalone_query,
            "top_k": top_k,
            "mode": mode,
            "filters": dict(query_plan.filters),
        }
        result = tool_executor.execute(
            tool_call_id=call_id,
            tool_name="search_documents",
            arguments=arguments,
            trace_id=trace_id,
            retrieval_attempt=1,
        )
        state.tool_calls.append(ToolCallRecord(
            iteration=0,
            tool_call_id=call_id,
            tool_name="search_documents",
            arguments=arguments,
            success=result.success,
            error_code=result.error_code,
        ))
        if not result.success:
            return self.runtime_support.result(
                state,
                StopReason.TOOL_ERROR,
                message=result.error_message or "检索暂时不可用，请稍后重试。",
                error_code=result.error_code or "retrieval_error",
            )
        state.retrieval_attempts = 1
        state.evidence = [item.model_dump() for item in result.evidence]

        gate_result = evidence_gate.evaluate(
            query_plan,
            policy,
            list(result.evidence),
            retrieval_attempt=1,
        )
        self.runtime_support.record_evidence_gate(state, gate_result)
        accepted = list(gate_result.evidence)
        if not gate_result.accepted and gate_result.should_retry:
            requests = corrective_retrieval.plan(
                query_plan,
                policy,
                gate_result,
                previous_mode=mode,
                previous_top_k=top_k,
            )
            corrected = list(result.evidence)
            for index, retry in enumerate(requests[:1], start=1):
                if len(state.tool_calls) >= policy.max_tool_calls:
                    return self.runtime_support.result(
                        state,
                        StopReason.POLICY_LIMIT,
                        message="Agent 已达到当前意图的工具调用预算。",
                        error_code="max_tool_calls",
                    )
                retry_id = f"fast-corrective-{trace_id}-{index}"
                retry_result = tool_executor.execute(
                    tool_call_id=retry_id,
                    tool_name="search_documents",
                    arguments={
                        "query": retry.query,
                        "top_k": retry.top_k,
                        "mode": retry.mode,
                        "filters": retry.filters,
                    },
                    trace_id=trace_id,
                    retrieval_attempt=retry.retrieval_attempt,
                )
                state.tool_calls.append(ToolCallRecord(
                    iteration=0,
                    tool_call_id=retry_id,
                    tool_name="search_documents",
                    arguments={
                        "query": retry.query,
                        "top_k": retry.top_k,
                        "mode": retry.mode,
                        "filters": retry.filters,
                    },
                    success=retry_result.success,
                    error_code=retry_result.error_code,
                ))
                if not retry_result.success:
                    return self.runtime_support.result(
                        state,
                        StopReason.TOOL_ERROR,
                        message=retry_result.error_message or "纠偏检索失败。",
                        error_code=retry_result.error_code or "retrieval_error",
                    )
                state.retrieval_attempts = 2
                corrected.extend(retry_result.evidence)
                state.evidence = [item.model_dump() for item in corrected]
            if state.retrieval_attempts == 2:
                gate_result = evidence_gate.evaluate(
                    query_plan,
                    policy,
                    corrected,
                    retrieval_attempt=2,
                )
                self.runtime_support.record_evidence_gate(state, gate_result)
                accepted = list(gate_result.evidence)

        if not gate_result.accepted:
            return self.runtime_support.result(
                state,
                StopReason.NO_RELEVANT_CONTEXT,
                message=self.runtime_support.insufficient_evidence_message(gate_result),
                error_code="insufficient_evidence",
            )
        state.evidence = [item.model_dump() for item in accepted]
        context_history = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in history
            if item.get("role") in {"system", "user", "assistant"}
            and isinstance(item.get("content"), str)
        ]
        messages, state.evidence = self.answer_generator.build_evidence_messages(
            query_plan,
            state.evidence,
            context_history,
            is_first_message=is_first_message,
            soul_content=soul_content,
        )
        return self._answer(state, policy, messages, preference="fast")

    def _answer(
        self,
        state: AgentState,
        policy: IntentPolicy,
        messages: list[dict[str, Any]],
        *,
        preference: str,
    ) -> AgentRunResult:
        try:
            response = self.answer_generator.chat(
                messages,
                query_plan=state.query_plan,
                retrieval_attempts=state.retrieval_attempts,
                trace_id=state.trace_id,
                preference=preference,  # type: ignore[arg-type]
            )
            if not isinstance(response, dict) or not isinstance(response.get("content"), str):
                raise ValueError("answer model returned an invalid response")
            answer = response["content"].strip()
            if not answer:
                raise ValueError("answer model returned an empty response")
            answer = self.runtime_support.check_and_repair_answer(
                state=state,
                policy=policy,
                answer=answer,
            )
            return self.runtime_support.result(
                state,
                StopReason.FINAL_ANSWER,
                answer=answer,
            )
        except Exception as exc:
            logger.exception("[FAST_LOOP_ERROR] trace_id=%s error=%s", state.trace_id, exc)
            return self.runtime_support.result(
                state,
                StopReason.LLM_ERROR,
                message="模型服务暂时不可用，请稍后重试。",
                error_code=exc.__class__.__name__,
            )

