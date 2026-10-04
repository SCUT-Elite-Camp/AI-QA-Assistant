"""Small runtime behaviors shared by Fast and Thinking execution."""

import logging
from typing import Any

from agent.answer import AnswerCompletenessChecker, should_accept_repair
from agent.evidence.schemas import EvidenceGateResult
from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE
from agent.runtime.state import AgentRunResult, AgentState, StopReason
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence

logger = logging.getLogger("agent-layer")


class RuntimeSupport:
    """Own shared message construction, result mapping, and answer checks."""

    def __init__(
        self,
        answer_completeness_checker: AnswerCompletenessChecker | None = None,
    ) -> None:
        self.answer_completeness_checker = answer_completeness_checker

    @staticmethod
    def record_evidence_gate(
        state: AgentState,
        result: EvidenceGateResult,
    ) -> None:
        """Project the final gate decision into shared run diagnostics."""
        state.evidence_gate_reason = result.reason
        state.covered_evidence_targets = list(result.covered_targets)
        state.missing_evidence_targets = list(result.missing_targets)
        state.eligible_evidence_count = result.eligible_evidence_count
        state.rejected_evidence_count = result.rejected_evidence_count
        logger.info(
            "[EVIDENCE_GATE] trace_id=%s accepted=%s reason=%s candidates=%s "
            "eligible=%s rejected=%s covered=%s missing=%s attempt=%s",
            state.trace_id,
            result.accepted,
            result.reason,
            result.candidate_evidence_count,
            result.eligible_evidence_count,
            result.rejected_evidence_count,
            result.covered_targets,
            result.missing_targets,
            result.retrieval_attempt,
        )

    @staticmethod
    def build_messages(
        query_plan: QueryPlan,
        history: list[dict[str, Any]],
        is_first_message: bool = False,
        soul_content: str | None = None,
        policy: IntentPolicy | None = None,
    ) -> list[dict[str, Any]]:
        title_directive = (
            "\n\n【极重要指令】：这是本对话的第一个提问。请务必在最终回答的第一行输出您总结的对话标题，格式必须为：[TITLE: 3-10字精炼标题]，然后再换行输出正文回答。"
            if is_first_message
            else ""
        )
        soul_directive = (
            f"\n\n【话题归属认知 (Topic Cognition - Soul.md)】:\n"
            f"当前对话运行在特定话题空间（Topic Workspace）内。以下是本话题的核心技术认知、领域实体与边界指引。在回答与使用检索工具时，请务必紧密结合此话题背景进行定位：\n"
            f"{soul_content}\n"
            if soul_content and soul_content.strip()
            else ""
        )
        system_content = (
            f"{SYSTEM_ROLE}\n\n"
            "你可以使用提供的工具获取回答所需的证据。"
            "工具返回后，基于观察结果给出最终答案；不要编造不存在的证据。\n\n"
            f"{soul_directive}\n"
            f"检索用独立查询：{query_plan.standalone_query}\n\n"
            f"回答约束：\n{ANSWER_RULES}"
            f"{RuntimeSupport.document_tool_guidance(policy)}"
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
        messages.append({"role": "user", "content": query_plan.original_query})
        return messages

    @staticmethod
    def document_tool_guidance(policy: IntentPolicy | None) -> str:
        tools = set(policy.candidate_tools) if policy is not None else set()
        if "wiki_search" in tools:
            return (
                "\n\n检索路由规则：先使用 Direct 工具（如 search_documents "
                "或 search_library）获取权威证据。服务端会通过覆盖率评估决定"
                "是否启动 Wiki；不要直接调用 Wiki 工具。启动后按 wiki_search "
                "-> wiki_read_page -> "
                "wiki_read_sources -> wiki_search_evidence 完成导航。Wiki 页面"
                "和关系元数据仅用于导航；最终结论只能引用原始 Evidence。"
            )
        if {"find_documents", "get_document"}.issubset(tools):
            return (
                "\n\n工具选择规则：未知 doc_id 时先用 find_documents 定位文档；"
                "已知 doc_id 且需要通读或摘要时用 get_document。"
                "get_document 返回 has_more=true 时，按 next_offset 继续分页读取；"
                "只需查找相关片段时用 search_documents。"
            )
        if "find_documents" in tools:
            return (
                "\n\n工具选择规则：使用 find_documents 查找或列出文档；"
                "其结果是文档身份与摘要，不得视为全文。"
            )
        if "search_attachments" in tools:
            return (
                "\n\n工具选择规则：先用 search_attachments 检索当前请求已授权附件；"
                "仅当文本/OCR 证据不足且需要理解图片或页面区域时，"
                "才使用 inspect_attachment。不得自行构造 attachment_id。"
            )
        return ""

    @staticmethod
    def insufficient_evidence_message(gate_result: Any) -> str:
        missing = ", ".join(gate_result.missing_targets) or "unspecified evidence"
        return (
            "Evidence remained insufficient after bounded retrieval "
            f"({gate_result.reason}); missing: {missing}."
        )

    @staticmethod
    def result(
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
            coverage_assessments=[
                assessment.model_dump(mode="json")
                for assessment in state.coverage_assessments
            ],
            exploration_rounds=state.exploration_rounds,
            messages=state.messages,
            error_code=error_code,
            evidence_gate_reason=state.evidence_gate_reason,
            covered_evidence_targets=state.covered_evidence_targets,
            missing_evidence_targets=state.missing_evidence_targets,
            eligible_evidence_count=state.eligible_evidence_count,
            rejected_evidence_count=state.rejected_evidence_count,
            answer_completeness_checked=state.answer_completeness_checked,
            answer_complete=state.answer_complete,
            missing_answer_aspects=state.missing_answer_aspects,
            missing_critical_facts=state.missing_critical_facts,
            answer_repair_attempted=state.answer_repair_attempted,
            answer_repair_rolled_back=state.answer_repair_rolled_back,
            answer_repair_guard_reason=state.answer_repair_guard_reason,
        )

    def check_and_repair_answer(
        self,
        *,
        state: AgentState,
        policy: IntentPolicy | None,
        answer: str,
    ) -> str:
        checker = self.answer_completeness_checker
        if checker is None or policy is None or not policy.requires_citations:
            return answer
        if not state.evidence:
            logger.info(
                "[ANSWER_COMPLETENESS] trace_id=%s skipped=no_accepted_evidence",
                state.trace_id,
            )
            state.answer_completeness_checked = False
            return answer

        try:
            typed_evidence = [Evidence.model_validate(item) for item in state.evidence]
            result = checker.check(state.query_plan, answer, typed_evidence)
            state.answer_completeness_checked = result.check_performed
            state.answer_complete = result.complete
            state.missing_answer_aspects = result.missing_aspects
            state.missing_critical_facts = result.missing_critical_facts
            logger.info(
                "[ANSWER_COMPLETENESS] trace_id=%s complete=%s missing_aspects=%s "
                "missing_critical_facts=%s coverage=%s",
                state.trace_id,
                result.complete,
                result.missing_aspects,
                result.missing_critical_facts,
                result.coverage,
            )
            if result.complete:
                return answer

            state.answer_repair_attempted = True
            repaired = checker.repair(state.query_plan, answer, typed_evidence, result)
            targets = result.required_targets or [
                *result.missing_aspects,
                *result.missing_critical_facts,
            ]
            accepted, reason = should_accept_repair(answer, repaired, targets)
            state.answer_repair_guard_reason = reason
            if not accepted:
                state.answer_repair_rolled_back = True
                logger.info(
                    "[ANSWER_COMPLETENESS] trace_id=%s repair_rolled_back=%s",
                    state.trace_id,
                    reason,
                )
                return answer
            state.answer_complete = True
            return repaired
        except Exception as exc:
            logger.warning(
                "[ANSWER_COMPLETENESS] trace_id=%s check_failed=%s; preserving original answer",
                state.trace_id,
                exc,
            )
            return answer
