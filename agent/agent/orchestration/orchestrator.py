"""Cross-component Agent orchestration for the CP2 request lifecycle."""

from dataclasses import dataclass
from typing import Any

from agent.config.settings import settings
from agent.evidence import CitationChecker, CitationCheckResult, EvidenceGate
from agent.memory import ConversationMemory
from agent.policy import IntentPolicyRouter
from agent.query import QueryUnderstanding
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import AgentRunResult, AgentRunner
from agent.schemas.chat import ChatRequest, Citation
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence
from agent.tools import ToolExecutor


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
        policy = self._apply_library_policy(request, policy)
        policy = self._apply_attachment_policy(request, policy)
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
    def _apply_library_policy(request: ChatRequest, policy: IntentPolicy) -> IntentPolicy:
        if not request.personal_library_context or policy.retrieval_strategy == "none":
            return policy
        candidates = tuple(dict.fromkeys((*policy.candidate_tools, "search_library")))
        return policy.model_copy(update={
            "candidate_tools": candidates,
            "max_tool_calls": min(10, max(2, policy.max_tool_calls + 1)),
            "max_iterations": min(10, max(2, policy.max_iterations + 1)),
        })

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
