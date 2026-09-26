"""Cross-component Agent orchestration for the CP2 request lifecycle."""

from dataclasses import dataclass
import os
from typing import Any

from agent.config.settings import settings
from agent.evidence import CitationChecker, CitationCheckResult, EvidenceGate
from agent.memory import ConversationMemory
from agent.memory.context_resolver import ContextResolver
from agent.memory.memory_response_policy import MemoryResponsePolicy
from agent.memory.persistent_models import PersistentMemoryContext
from agent.policy import IntentPolicyRouter
from agent.query import QueryUnderstanding, heuristic_source_intent
from agent.query.subquery_router import SubQueryRouter
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import AgentRunResult, AgentRunner
from agent.schemas.chat import (
    AttachmentContext,
    ChatRequest,
    Citation,
    ContextArtifact,
    MemoryContextInput,
    MemoryRecall,
    PersonalLibraryContext,
)
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent, SourceKind
from agent.schemas.subquery_routing import SubQueryRoutingResult
from agent.schemas.tool_execution import Evidence
from agent.tools import ToolExecutor


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
        source_intent = (
            plan.source_intent
            if plan.source_intent.sources
            else heuristic_source_intent(plan.original_query)
        )
        attachment_context = getattr(request, "attachment_context", None)
        if (
            isinstance(attachment_context, AttachmentContext)
            and attachment_context.selected_attachment_ids
            and SourceKind.CONVERSATION_ATTACHMENT not in source_intent.sources
        ):
            source_intent = source_intent.model_copy(update={
                "sources": [
                    SourceKind.CONVERSATION_ATTACHMENT,
                    *source_intent.sources,
                ]
            })
        plan = plan.model_copy(update={"source_intent": source_intent})
        policy = self._apply_source_policy(
            request,
            self.policy_router.route(plan),
            source_intent,
        )
        navigation_scopes = self._navigation_scopes(request, source_intent)
        policy = self._apply_exploration_policy(
            request,
            plan,
            policy,
            navigation_scopes=navigation_scopes,
        )
        subquery_routing = (
            self.subquery_router.route(plan)
            if self.subquery_router is not None
            else SubQueryRoutingResult(is_complex=len(plan.sub_queries) >= 2)
        )
        retrieval_mode, top_k = self._effective_retrieval_options(
            request,
            policy,
        )
        is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)
        context_tools = self._configure_tool_contexts(request)
        try:
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
                soul_content=request.soul_content,
                exploration_mode=request.exploration_mode,
                navigation_scopes=navigation_scopes,
            )
        finally:
            for tool in context_tools:
                tool.clear_request_context()
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

    def _configure_library_context(self, request: ChatRequest) -> Any | None:
        tool = self.tool_executor.registry.get("search_library")
        context = getattr(request, "personal_library_context", None)
        if (
            tool is None
            or not hasattr(tool, "set_request_context")
            or not isinstance(context, PersonalLibraryContext)
        ):
            return None
        tool.set_request_context(
            context.owner_user_id,
            context.knowledge_base_id,
            context.access_token,
        )
        return tool

    def _configure_tool_contexts(self, request: ChatRequest) -> list[Any]:
        configured: list[Any] = []
        library_tool = self._configure_library_context(request)
        if library_tool is not None:
            configured.append(library_tool)

        personal = getattr(request, "personal_library_context", None)
        for name in (
            "wiki_search", "wiki_read_page", "wiki_read_sources",
            "wiki_search_evidence",
        ):
            tool = self.tool_executor.registry.get(name)
            if tool is None or not hasattr(tool, "set_personal_context"):
                continue
            tool.set_personal_context(
                personal.owner_user_id if isinstance(personal, PersonalLibraryContext) else "",
                personal.knowledge_base_id if isinstance(personal, PersonalLibraryContext) else "",
                personal.access_token if isinstance(personal, PersonalLibraryContext) else "",
                secret=os.getenv("ATTACHMENT_INTERNAL_SECRET", ""),
            )
            configured.append(tool)

        context = getattr(request, "attachment_context", None)
        if not isinstance(context, AttachmentContext):
            return configured
        for name in ("search_attachments", "inspect_attachment"):
            tool = self.tool_executor.registry.get(name)
            if tool is None or not hasattr(tool, "set_request_context"):
                continue
            tool.set_request_context(
                context.allowed_attachment_ids,
                context.selected_attachment_ids,
            )
            configured.append(tool)
        return configured

    @staticmethod
    def _apply_source_policy(
        request: ChatRequest,
        policy: IntentPolicy,
        source_intent: SourceIntent,
    ) -> IntentPolicy:
        sources = set(source_intent.sources)
        if not request.knowledge_base_retrieval_enabled:
            sources.difference_update({
                SourceKind.ENTERPRISE_KB,
                SourceKind.PERSONAL_LIBRARY,
            })
            knowledge_tools = {
                "search_documents",
                "find_documents",
                "get_document",
                "search_library",
                "wiki_search",
                "wiki_read_page",
                "wiki_read_sources",
                "wiki_search_evidence",
            }
            policy = policy.model_copy(update={
                "candidate_tools": tuple(
                    tool
                    for tool in policy.candidate_tools
                    if tool not in knowledge_tools
                ),
            })
        if not sources:
            return policy

        tools: list[str] = []
        if SourceKind.ENTERPRISE_KB in sources:
            tools.extend(policy.candidate_tools)
        if (
            SourceKind.PERSONAL_LIBRARY in sources
            and isinstance(
                getattr(request, "personal_library_context", None),
                PersonalLibraryContext,
            )
        ):
            tools.append("search_library")
        if (
            SourceKind.CONVERSATION_ATTACHMENT in sources
            and isinstance(
                getattr(request, "attachment_context", None),
                AttachmentContext,
            )
        ):
            tools.extend(("search_attachments", "inspect_attachment"))
        tools = list(dict.fromkeys(tools))

        private_sources = {
            SourceKind.PERSONAL_LIBRARY,
            SourceKind.CONVERSATION_ATTACHMENT,
        }
        if not sources.intersection(private_sources):
            return policy.model_copy(update={"candidate_tools": tuple(tools)})
        return policy.model_copy(update={
            "candidate_tools": tuple(tools),
            "retrieval_strategy": "hybrid",
            "evidence_policy": (
                "single_fact" if policy.evidence_policy == "none" else policy.evidence_policy
            ),
            "assembly_strategy": (
                "score_order" if policy.assembly_strategy == "none" else policy.assembly_strategy
            ),
            "top_k": max(5, policy.top_k),
            "max_iterations": max(2, policy.max_iterations),
            "max_tool_calls": max(
                2 if SourceKind.CONVERSATION_ATTACHMENT in sources else 1,
                policy.max_tool_calls,
            ),
            "max_retrieval_attempts": (
                2
                if sources.intersection({
                    SourceKind.ENTERPRISE_KB,
                    SourceKind.CONVERSATION_ATTACHMENT,
                })
                else 1
            ),
            "requires_citations": True,
        })

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
            "max_iterations": max(
                policy.max_iterations, settings.EXPLORATION_MAX_ROUNDS + 2
            ),
            "max_tool_calls": max(
                policy.max_tool_calls, settings.EXPLORATION_MAX_TOOL_CALLS
            ),
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
        selected = set(source_intent.sources)
        scopes: list[str] = []
        if (
            request.knowledge_base_retrieval_enabled
            and SourceKind.ENTERPRISE_KB in selected
        ):
            scopes.append("enterprise")
        if (
            request.knowledge_base_retrieval_enabled
            and getattr(request, "personal_library_context", None) is not None
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
            if key in merged_filters and merged_filters[key] != value:
                raise ValueError(f"conflicting hard filter: {key}")
            merged_filters[key] = value
        return query_plan.model_copy(update={"filters": merged_filters})

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
