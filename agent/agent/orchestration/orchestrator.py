"""Cross-component Agent orchestration for the CP2 request lifecycle."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from agent.config.settings import settings
from agent.evidence import CitationChecker, CitationCheckResult, EvidenceGate
from agent.memory import ConversationMemory
from agent.memory.context_resolver import ContextResolver
from agent.memory.memory_response_policy import MemoryResponsePolicy
from agent.memory.persistent_models import PersistentMemoryContext
from agent.policy import IntentPolicyRouter
from agent.query import QueryUnderstanding
from agent.query.source_intent import heuristic_source_intent
from agent.query.subquery_router import SubQueryRouter
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import AgentRunResult, AgentRunner
from agent.schemas.chat import (
    ChatRequest,
    Citation,
    ContextArtifact,
    MemoryContextInput,
    MemoryRecall,
)
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent, SourceKind
from agent.schemas.subquery_routing import SubQueryRoutingResult
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
    run_result: AgentRunResult | None
    history: list[dict[str, Any]]
    retrieval_mode: str
    top_k: int
    subquery_routing: SubQueryRoutingResult
    context_artifact: ContextArtifact | None = None
    memory_recall: MemoryRecall | None = None


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
        subquery_router: SubQueryRouter | None = None,
        context_resolver: ContextResolver | None = None,
        memory_response_policy: MemoryResponsePolicy | None = None,
    ) -> None:
        self.memory = memory
        self.query_understanding = query_understanding
        self.policy_router = policy_router
        self.runner = runner
        self.tool_executor = tool_executor
        self.evidence_gate = evidence_gate
        self.corrective_retrieval = corrective_retrieval
        self.citation_checker = citation_checker
        self.context_resolver = context_resolver or ContextResolver()
        self.memory_response_policy = memory_response_policy or MemoryResponsePolicy()
        classifier = getattr(query_understanding, "intent_classifier", None)
        self.subquery_router = subquery_router
        if self.subquery_router is None and classifier is not None:
            self.subquery_router = SubQueryRouter(classifier, policy_router)

    def run(
        self,
        request: ChatRequest,
        *,
        trace_id: str,
        query_plan: QueryPlan | None = None,
    ) -> OrchestrationResult:
        """Run the complete CP2 Agent pipeline for one Chat request."""

        context_artifact, memory_recall = self._resolve_persistent_memory(request)
        history = (
            self._history_from_context_artifact(context_artifact)
            if context_artifact is not None
            else self._read_history(request.session_id)
        )
        if memory_recall is not None and memory_recall.handled:
            plan = self._resolve_recall_query_plan(request, query_plan)
            policy = self.policy_router.route(plan)
            retrieval_mode, top_k = self._effective_retrieval_options(request, policy)
            return OrchestrationResult(
                query_plan=plan,
                policy=policy,
                run_result=None,
                history=history,
                retrieval_mode=retrieval_mode,
                top_k=top_k,
                subquery_routing=SubQueryRoutingResult(),
                context_artifact=context_artifact,
                memory_recall=memory_recall,
            )

        plan = self._resolve_query_plan(request, query_plan, history)
        policy = self.policy_router.route(plan)
        subquery_routing = (
            self.subquery_router.route(plan)
            if self.subquery_router is not None
            else SubQueryRoutingResult(is_complex=len(plan.sub_queries) >= 2)
        )
        heuristic_intent, effective_intent, routing_mode = self._resolve_source_intent(
            request,
            plan,
            trace_id,
        )
        policy = self._apply_source_policy(request, policy, effective_intent)
        policy = self._apply_knowledge_base_policy(request, policy)
        navigation_scopes = self._navigation_scopes(
            request,
            effective_intent,
        )
        policy = self._apply_exploration_policy(
            request,
            plan,
            policy,
            navigation_scopes=navigation_scopes,
        )
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
            corrective_retrieval=(
                self.corrective_retrieval
                if request.knowledge_base_retrieval_enabled
                else None
            ),
            history=history,
            trace_id=trace_id,
            mode=retrieval_mode,
            top_k=top_k,
            is_first_message=is_first,
            soul_content=request.soul_content,
            exploration_mode=request.exploration_mode,
            navigation_scopes=navigation_scopes,
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
            subquery_routing=subquery_routing,
            context_artifact=context_artifact,
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

    @staticmethod
    def _apply_exploration_policy(
        request: ChatRequest,
        plan: QueryPlan,
        policy: IntentPolicy,
        *,
        navigation_scopes: tuple[str, ...] = (),
    ) -> IntentPolicy:
        if (
            not settings.AGENTIC_EXPLORATION_ENABLED
            or request.exploration_mode == "off"
            or not policy_requires_retrieval(plan)
            or not navigation_scopes
        ):
            return policy
        candidates = list(policy.candidate_tools)
        if settings.KNOWLEDGE_NAVIGATION_ENABLED:
            candidates.extend((
                "wiki_search", "wiki_read_page", "wiki_read_sources",
                "wiki_search_evidence",
            ))
        return policy.model_copy(update={
            "candidate_tools": tuple(dict.fromkeys(candidates)),
            "max_iterations": max(policy.max_iterations, settings.EXPLORATION_MAX_ROUNDS + 2),
            "max_tool_calls": max(policy.max_tool_calls, settings.EXPLORATION_MAX_TOOL_CALLS),
            # Mandatory Direct retrieval is outside the exploration-round
            # budget; leave room for enterprise/personal Direct plus 3 steps.
            "max_retrieval_attempts": max(
                policy.max_retrieval_attempts,
                min(5, settings.EXPLORATION_MAX_ROUNDS + 2),
            ),
        })

    @staticmethod
    def _navigation_scopes(
        request: ChatRequest,
        source_intent: SourceIntent,
    ) -> tuple[str, ...]:
        """Resolve server-authorized exploration scopes for this request."""
        selected = set(source_intent.sources)
        scopes: list[str] = []
        if (
            request.knowledge_base_retrieval_enabled
            and SourceKind.ENTERPRISE_KB in selected
        ):
            scopes.append("enterprise")
        if (
            request.knowledge_base_retrieval_enabled
            and request.personal_library_context is not None
            and SourceKind.PERSONAL_LIBRARY in selected
        ):
            scopes.append("personal")
        return tuple(scopes)

    def _read_history(self, session_id: str | None) -> list[dict[str, Any]]:
        if not settings.MEMORY_ENABLED or not session_id:
            return []
        return self.memory.get_messages(session_id)

    def _resolve_persistent_memory(
        self,
        request: ChatRequest,
    ) -> tuple[ContextArtifact | None, MemoryRecall | None]:
        memory_context = getattr(request, "memory_context", None)
        if not isinstance(memory_context, MemoryContextInput):
            return None, None

        artifact = self.context_resolver.resolve(memory_context)
        if artifact is None:
            return None, None

        persistent_context = PersistentMemoryContext.from_input(memory_context)
        return artifact, self.memory_response_policy.resolve(
            request.query,
            persistent_context.facts,
        )

    @staticmethod
    def _history_from_context_artifact(
        artifact: ContextArtifact,
    ) -> list[dict[str, Any]]:
        return [
            {"role": message.role, "content": message.content}
            for message in artifact.model_history
        ]

    @staticmethod
    def _resolve_recall_query_plan(
        request: ChatRequest,
        query_plan: QueryPlan | None,
    ) -> QueryPlan:
        if query_plan is not None:
            return AgentOrchestrator._merge_request_constraints(request, query_plan)
        return QueryPlan(
            original_query=request.query,
            standalone_query=request.query.strip(),
            filters=dict(request.filters or {}),
        )

    def _resolve_query_plan(
        self,
        request: ChatRequest,
        query_plan: QueryPlan | None,
        history: list[dict[str, Any]],
    ) -> QueryPlan:
        if query_plan is not None:
            return self._merge_request_constraints(request, query_plan)

        effective_history = list(history)
        if not history and request.soul_content:
            # Inject short topic summary context hint into history for query rewriter / planner
            effective_history.insert(0, {
                "role": "user",
                "content": f"[Topic Workspace Cognition Context]:\n{request.soul_content[:600]}"
            })

        analyzed_plan = self.query_understanding.analyze(
            request.query,
            effective_history,
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
        if (
            request.attachment_context
            and request.attachment_context.selected_attachment_ids
        ):
            if SourceKind.CONVERSATION_ATTACHMENT not in heuristic.sources:
                heuristic = heuristic.model_copy(
                    update={
                        "sources": [
                            *heuristic.sources,
                            SourceKind.CONVERSATION_ATTACHMENT,
                        ]
                    }
                )
            if SourceKind.CONVERSATION_ATTACHMENT not in structured.sources:
                structured = structured.model_copy(
                    update={
                        "sources": [
                            *structured.sources,
                            SourceKind.CONVERSATION_ATTACHMENT,
                        ]
                    }
                )
        mode = settings.SOURCE_INTENT_ROUTING_MODE
        if mode in {"heuristic", "shadow"} or not structured.sources:
            return heuristic, heuristic, mode
        if mode == "canary":
            identity = request.session_id or trace_id or request.query
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
    def _apply_knowledge_base_policy(
        request: ChatRequest,
        policy: IntentPolicy,
    ) -> IntentPolicy:
        """Honor the caller's per-turn enterprise/library retrieval choice."""
        if request.knowledge_base_retrieval_enabled:
            return policy

        knowledge_tools = {
            "search_documents",
            "find_documents",
            "get_document",
            "search_library",
        }
        candidates = tuple(
            tool for tool in policy.candidate_tools if tool not in knowledge_tools
        )
        if any(
            tool in {"search_attachments", "inspect_attachment"}
            for tool in candidates
        ):
            return policy.model_copy(update={"candidate_tools": candidates})

        return policy.model_copy(
            update={
                "candidate_tools": candidates,
                "retrieval_strategy": "none",
                "evidence_policy": "none",
                "assembly_strategy": "none",
                "answer_style": "direct_chat",
                "top_k": 0,
                "max_iterations": 1,
                "max_tool_calls": 0,
                "max_retrieval_attempts": 0,
                "requires_citations": False,
            }
        )

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
