"""Cross-component Agent orchestration for the CP2 request lifecycle."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from agent.config.settings import settings
from agent.evidence import CitationChecker, CitationCheckResult, EvidenceGate
from agent.memory import ConversationMemory
from agent.policy import IntentPolicyRouter
from agent.query import QueryUnderstanding
from agent.query.source_intent import heuristic_source_intent
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import AgentRunResult, AgentRunner
from agent.schemas.chat import ChatRequest, Citation
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent, SourceKind
from agent.schemas.tool_execution import Evidence
from agent.tools import ToolExecutor


logger = logging.getLogger("agent-layer.source-intent")


def policy_requires_retrieval(plan: QueryPlan) -> bool:
    return plan.intent in {
        QueryIntent.KNOWLEDGE_QA,
        QueryIntent.DOCUMENT_SEARCH,
        QueryIntent.SUMMARIZATION,
        QueryIntent.COMPARISON,
    }


@dataclass(frozen=True)
class OrchestrationResult:
    """All internal artifacts produced by one orchestrated request."""

    query_plan: QueryPlan
    policy: IntentPolicy
    run_result: AgentRunResult
    history: list[dict[str, Any]]
    retrieval_mode: str
    top_k: int


class AgentOrchestrator:
    """Coordinate memory, query understanding, policy, and runtime execution.

    The orchestrator deliberately owns the order of cross-workstream calls.
    Individual components remain injectable so unit tests and future backends
    can replace them without changing the public Chat API.
    """

    def __init__(
        self,
        *,
        memory: ConversationMemory,
        query_understanding: QueryUnderstanding,
        policy_router: IntentPolicyRouter,
        runner: AgentRunner,
        tool_executor: ToolExecutor,
        evidence_gate: EvidenceGate,
        corrective_retrieval: CorrectiveRetrievalPlanner,
        citation_checker: CitationChecker,
    ) -> None:
        self.memory = memory
        self.query_understanding = query_understanding
        self.policy_router = policy_router
        self.runner = runner
        self.tool_executor = tool_executor
        self.evidence_gate = evidence_gate
        self.corrective_retrieval = corrective_retrieval
        self.citation_checker = citation_checker

    def run(
        self,
        request: ChatRequest,
        *,
        trace_id: str,
        query_plan: QueryPlan | None = None,
    ) -> OrchestrationResult:
        """Run the complete CP2 Agent pipeline for one Chat request."""

        history = self._read_history(request.session_id)
        plan = self._resolve_query_plan(request, query_plan, history)
        policy = self.policy_router.route(plan)
        heuristic_intent, effective_intent, routing_mode = self._resolve_source_intent(
            request,
            plan,
            trace_id,
        )
        policy = self._apply_source_policy(request, policy, effective_intent)
        retrieval_mode, top_k = self._effective_retrieval_options(
            request,
            policy,
        )
        is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)
        run_result = self.runner.run(
            plan,
            policy=policy,
            tool_executor=self.tool_executor,
            evidence_gate=self.evidence_gate,
            corrective_retrieval=self.corrective_retrieval,
            history=history,
            trace_id=trace_id,
            mode=retrieval_mode,
            top_k=top_k,
            is_first_message=is_first,
        )
        self._log_source_routing(
            request=request,
            trace_id=trace_id,
            routing_mode=routing_mode,
            heuristic_intent=heuristic_intent,
            structured_intent=plan.source_intent,
            effective_intent=effective_intent,
            policy=policy,
            evidence=run_result.evidence,
        )
        return OrchestrationResult(
            query_plan=plan,
            policy=policy,
            run_result=run_result,
            history=history,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
        )

    def validate_citations(
        self,
        answer: str,
        citations: list[Citation],
        evidence: list[dict[str, Any]],
    ) -> CitationCheckResult:
        """Validate the public citations against request-local Evidence."""

        typed_evidence: list[Evidence] = []
        for item in evidence:
            try:
                typed_evidence.append(Evidence.model_validate(item))
            except (TypeError, ValueError):
                # Legacy/direct Runner calls may return CP1-shaped evidence.
                # The normal orchestrated path always returns typed Evidence.
                continue
        return self.citation_checker.validate(answer, citations, typed_evidence)

    def _read_history(self, session_id: str | None) -> list[dict[str, Any]]:
        if not settings.MEMORY_ENABLED or not session_id:
            return []
        return self.memory.get_messages(session_id)

    def _resolve_query_plan(
        self,
        request: ChatRequest,
        query_plan: QueryPlan | None,
        history: list[dict[str, Any]],
    ) -> QueryPlan:
        if query_plan is not None:
            return self._merge_request_constraints(request, query_plan)

        analyzed_plan = self.query_understanding.analyze(
            request.query,
            history,
            filters=request.filters,
        )
        return self._merge_request_constraints(request, analyzed_plan)

    @staticmethod
    def _merge_request_constraints(
        request: ChatRequest,
        query_plan: QueryPlan,
    ) -> QueryPlan:
        if query_plan.original_query != request.query:
            raise ValueError(
                "QueryPlan.original_query must exactly match ChatRequest.query"
            )

        merged_filters = dict(query_plan.filters)
        for key, value in (request.filters or {}).items():
            # Request filters are explicit caller constraints and therefore
            # take precedence over filters inferred by QueryPlanner.
            merged_filters[key] = value
        return query_plan.model_copy(update={"filters": merged_filters})

    @staticmethod
    def _resolve_source_intent(
        request: ChatRequest,
        plan: QueryPlan,
        trace_id: str,
    ) -> tuple[SourceIntent, SourceIntent, str]:
        heuristic = heuristic_source_intent(
            request.query,
            enterprise_default=policy_requires_retrieval(plan),
        )
        structured = plan.source_intent
        mode = settings.SOURCE_INTENT_ROUTING_MODE
        if mode in {"heuristic", "shadow"} or not structured.sources:
            return heuristic, heuristic, mode
        if mode == "canary":
            identity = trace_id or request.session_id or request.query
            bucket = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16) % 100
            if bucket >= settings.SOURCE_INTENT_CANARY_PERCENT:
                return heuristic, heuristic, mode
        return heuristic, structured, mode

    @staticmethod
    def _apply_source_policy(
        request: ChatRequest,
        policy: IntentPolicy,
        source_intent: SourceIntent,
    ) -> IntentPolicy:
        selected = set(source_intent.sources)
        source_tools = {
            "search_documents",
            "find_documents",
            "get_document",
            "search_library",
            "search_attachments",
            "inspect_attachment",
        }
        candidates = [tool for tool in policy.candidate_tools if tool not in source_tools]
        if SourceKind.ENTERPRISE_KB in selected:
            enterprise = [tool for tool in policy.candidate_tools if tool in {
                "search_documents", "find_documents", "get_document",
            }]
            candidates.extend(enterprise or ["search_documents"])
        if SourceKind.PERSONAL_LIBRARY in selected and request.personal_library_context:
            candidates.append("search_library")
        attachment_context = request.attachment_context
        if (
            SourceKind.CONVERSATION_ATTACHMENT in selected
            and attachment_context
            and attachment_context.allowed_attachment_ids
        ):
            candidates.extend(("search_attachments", "inspect_attachment"))
        candidates_tuple = tuple(dict.fromkeys(candidates))
        updates: dict[str, Any] = {
            "candidate_tools": candidates_tuple,
        }
        added_source_count = len([tool for tool in candidates_tuple if tool in source_tools])
        if added_source_count:
            updates.update(
                max_tool_calls=min(10, max(2, policy.max_tool_calls + added_source_count)),
                max_iterations=min(10, max(2, policy.max_iterations + added_source_count)),
                max_retrieval_attempts=min(5, max(2, policy.max_retrieval_attempts + 1)),
            )
        if added_source_count and policy.retrieval_strategy == "none":
            updates.update(
                retrieval_strategy="hybrid",
                evidence_policy="single_fact",
                assembly_strategy="score_order",
                answer_style="concise_qa",
                top_k=5,
                max_retrieval_attempts=2,
                requires_citations=True,
            )
        if (
            SourceKind.CONVERSATION_ATTACHMENT in selected
            and attachment_context
            and attachment_context.selected_attachment_ids
        ):
            updates.update(
                max_tool_calls=max(5, int(updates.get("max_tool_calls", policy.max_tool_calls))),
                max_iterations=max(5, int(updates.get("max_iterations", policy.max_iterations))),
                max_retrieval_attempts=max(
                    5,
                    int(updates.get("max_retrieval_attempts", policy.max_retrieval_attempts)),
                ),
            )
        return policy.model_copy(update=updates)

    @staticmethod
    def _apply_library_policy(request: ChatRequest, policy: IntentPolicy) -> IntentPolicy:
        """One-release compatibility wrapper for callers of the old heuristic."""
        intent = heuristic_source_intent(
            request.query,
            enterprise_default=policy.retrieval_strategy != "none",
        )
        return AgentOrchestrator._apply_source_policy(request, policy, intent)

    @staticmethod
    def _log_source_routing(
        *,
        request: ChatRequest,
        trace_id: str,
        routing_mode: str,
        heuristic_intent: SourceIntent,
        structured_intent: SourceIntent,
        effective_intent: SourceIntent,
        policy: IntentPolicy,
        evidence: list[dict[str, Any]],
    ) -> None:
        citation_sources = sorted({
            str(item.get("source_scope") or item.get("source_type") or "unknown")
            for item in evidence
        })
        logger.info(
            "[SOURCE_INTENT] trace_id=%s query_hash=%s mode=%s heuristic=%s "
            "structured=%s effective=%s tools=%s evidence_sources=%s",
            trace_id,
            hashlib.sha256(request.query.encode("utf-8")).hexdigest()[:16],
            routing_mode,
            [source.value for source in heuristic_intent.sources],
            [source.value for source in structured_intent.sources],
            [source.value for source in effective_intent.sources],
            list(policy.candidate_tools),
            citation_sources,
        )

    @staticmethod
    def _apply_attachment_policy(
        request: ChatRequest,
        policy: IntentPolicy,
    ) -> IntentPolicy:
        context = request.attachment_context
        if not context or not context.allowed_attachment_ids:
            return policy

        explicitly_selected = bool(context.selected_attachment_ids)
        retrieval_enabled = policy.retrieval_strategy != "none"
        if not explicitly_selected and not retrieval_enabled:
            # Merely having access to Topic attachments must not turn casual
            # chat or system-help requests into retrieval requests.
            return policy

        candidates = tuple(
            dict.fromkeys(
                (*policy.candidate_tools, "search_attachments", "inspect_attachment")
            )
        )
        updates: dict[str, Any] = {
            "candidate_tools": candidates,
            "max_tool_calls": min(10, max(2, policy.max_tool_calls + 2)),
            "max_iterations": min(10, max(2, policy.max_iterations + 2)),
            "max_retrieval_attempts": min(
                5,
                max(2, policy.max_retrieval_attempts + 2),
            ),
        }
        if explicitly_selected and not retrieval_enabled:
            # An explicitly selected attachment is request-local evidence.
            # It must override a mistaken zero-tool intent classification,
            # while the request allowlist still constrains every tool call.
            updates.update(
                retrieval_strategy="hybrid",
                evidence_policy="single_fact",
                assembly_strategy="score_order",
                answer_style="concise_qa",
                top_k=max(5, policy.top_k),
                requires_citations=True,
            )
        if explicitly_selected:
            # A selected multimodal attachment may require lexical/OCR search
            # followed by one deep-vision inspection and a final synthesis.
            updates.update(
                max_tool_calls=max(5, updates["max_tool_calls"]),
                max_iterations=max(5, updates["max_iterations"]),
                max_retrieval_attempts=max(
                    5,
                    updates["max_retrieval_attempts"],
                ),
            )
        return policy.model_copy(update=updates)

    @staticmethod
    def _effective_retrieval_options(
        request: ChatRequest,
        policy: IntentPolicy,
    ) -> tuple[str, int]:
        if policy.retrieval_strategy == "none":
            return request.retrieval_mode, 0

        # The request may lower top_k, while the policy remains the upper bound.
        top_k = min(request.top_k, policy.top_k) if policy.top_k else 0
        if top_k < 1:
            top_k = 1

        # Hybrid is the general default; specialized policies (e.g. document
        # search) are allowed to select their own retrieval strategy.
        mode = (
            policy.retrieval_strategy
            if policy.retrieval_strategy != "hybrid"
            else request.retrieval_mode
        )
        return mode, top_k
