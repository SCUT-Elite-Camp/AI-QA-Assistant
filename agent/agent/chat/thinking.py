"""Trusted Memory and source capabilities enter one bounded Agent loop."""
from agent.chat.sources import selected_sources
from agent.chat.result import OrchestrationResult
from agent.evidence import CitationChecker, EvidenceGate
from agent.memory.coordinator import MemoryCoordinator
from agent.runtime.profile import ExecutionProfileResolver
from agent.schemas.query_plan import QueryPlan, SourceIntent, SourceKind
from agent.schemas.tool_execution import Evidence


class ThinkingPipeline:
    def __init__(self, *, runner, tool_executor, memory_coordinator=None,
                 evidence_gate=None, citation_checker=None):
        self.runner, self.tool_executor = runner, tool_executor
        self.memory_coordinator = memory_coordinator or MemoryCoordinator()
        self.evidence_gate = evidence_gate or EvidenceGate()
        self.citation_checker = citation_checker or CitationChecker()

    def run(self, request, *, trace_id, query_plan=None):
        if request.weight_mode in {None, "fast"}:
            raise ValueError("Fast requests must enter FastPipeline")
        if query_plan is not None and (query_plan.original_query != request.query or any(
            key in query_plan.filters and query_plan.filters[key] != value
            for key, value in (request.filters or {}).items())):
            raise ValueError("conflicting_query_constraints")
        sources = selected_sources(request, query_plan)
        plan = QueryPlan(original_query=request.query, standalone_query=request.query,
            filters=self._merge_request_constraints(request, query_plan).filters if query_plan else dict(request.filters or {}),
            source_intent=SourceIntent(sources=sources))
        # Structural source selection is trusted input, not semantic classification.
        required = set(sources) if getattr(request, "retrieval_sources", None) is not None or (
            query_plan is not None and query_plan.source_intent.sources) else set()
        attachments = getattr(request, "attachment_context", None)
        if attachments and attachments.selected_attachment_ids:
            required.add(SourceKind.CONVERSATION_ATTACHMENT)
        source_types = {SourceKind.ENTERPRISE_KB: "knowledge", SourceKind.PERSONAL_LIBRARY: "personal",
                        SourceKind.CONVERSATION_ATTACHMENT: "attachment"}
        capabilities = {SourceKind.ENTERPRISE_KB: ("search_documents", "find_documents", "get_document"),
                        SourceKind.PERSONAL_LIBRARY: ("search_library",),
                        SourceKind.CONVERSATION_ATTACHMENT: ("search_attachments", "read_attachment_context")}
        memory = self.memory_coordinator.prepare(request)
        run_result = self.runner.run(plan, trace_id=trace_id, history=memory.history_for_model(),
            mode=request.retrieval_mode, top_k=request.top_k, tool_executor=self.tool_executor,
            evidence_gate=self.evidence_gate,
            allowed_tools=tuple(name for source in sources for name in capabilities[source]),
            required_sources=tuple(source_types[source] for source in required),
            required_attachments=tuple(attachments.selected_attachment_ids) if attachments else (),
            require_evidence=bool(sources), soul_content=request.soul_content)
        return OrchestrationResult(query_plan=plan, run_result=run_result,
            history=memory.history_for_model(), retrieval_mode=request.retrieval_mode, top_k=request.top_k,
            context_artifact=memory.context_artifact,
            execution_profile=ExecutionProfileResolver().resolve(request.weight_mode, exploration_mode=request.exploration_mode))

    def validate_citations(self, answer, citations, evidence):
        return self.citation_checker.validate(answer, citations, [Evidence.model_validate(item) for item in evidence])

    @staticmethod
    def _merge_request_constraints(request, plan):
        inferred = dict(plan.filters)
        hard = dict(request.filters or {})
        if "doc_ids" in hard:
            # Explicit source selections are authoritative; no guessed titles or
            # metadata may replace them or silently exclude selected sources.
            for key in ("doc_id", "document_id", "space", "doc_type"):
                if key not in hard:
                    inferred.pop(key, None)
        if any(key in inferred and inferred[key] != value for key, value in hard.items()):
            raise ValueError("conflicting_query_constraints")
        return plan.model_copy(update={"filters": {**inferred, **hard}})
