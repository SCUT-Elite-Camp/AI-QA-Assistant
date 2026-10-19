import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

from agent.chat.fast import FastPipeline
from agent.chat.thinking import ThinkingPipeline
from agent.config.settings import settings
from agent.evidence import CitationChecker, EvidenceGate
from agent.evidence.locator import canonical_chunk_id
from agent.formatter.answer_formatter import AnswerFormatter
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.llm.observability import (
    ObservedLLM,
    clear_llm_metrics,
    snapshot_llm_metrics,
    start_llm_metrics,
)
from agent.memory.coordinator import MemoryCoordinator
from agent.memory.fact_proposal_policy import FactProposalPolicy
from agent.memory.memory_observability import MemoryObservability
from agent.chat.result import OrchestrationResult
from agent.runtime import AgentRunResult, AgentRunner, StopReason
from agent.runtime.profile import ExecutionMode, ExecutionProfile
from agent.schemas.chat import ChatRequest, ChatResponse, FactProposal, InternalChatRequest, MemoryDecision
from agent.schemas.common import StatusCode
from agent.schemas.query_plan import QueryPlan
from agent.schemas.retrieval import RetrievalResult
from agent.service import AuditService, PermissionService, TraceService
from agent.service.access_guard import AccessGuard, CURRENT_ACCESS_GUARD, check_model_access
from agent.streaming.sse import chat_response_events
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool, SearchTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry


logger = logging.getLogger("agent-layer")


@dataclass(frozen=True)
class AgentChatExecution:
    """Request-local result retained across response and audit assembly."""

    response: ChatResponse
    orchestration: OrchestrationResult | None = None


class Agent:
    """Chat orchestrator for trusted Memory, permissions, and bounded execution."""

    def __init__(
        self,
        llm: BaseLLM | None = None,
        tools: list[BaseTool] | None = None,
        answer_formatter: AnswerFormatter | None = None,
        memory_coordinator: MemoryCoordinator | None = None,
        runner: AgentRunner | None = None,
        tool_executor: ToolExecutor | None = None,
        evidence_gate: EvidenceGate | None = None,
        citation_checker: CitationChecker | None = None,
        orchestrator: ThinkingPipeline | None = None,
        permission_service: PermissionService | None = None,
        toolset_registry: ToolsetRegistry | None = None,
        audit_service: AuditService | None = None,
        fact_proposal_policy: FactProposalPolicy | None = None,
        memory_observability: MemoryObservability | None = None,
    ) -> None:
        custom_llm_supplied = llm is not None
        self.llm = llm or LLMClient(fallback_models=(), attempts_per_model=1, retry_delay_seconds=0)
        self.runtime_llm = ObservedLLM(self.llm, "agent_runtime")
        # A Fast client has exactly one provider attempt and no fallback models,
        # even when both modes use the same model ID. Injected clients stay injectable.
        fast_model = self.llm if custom_llm_supplied else LLMClient(
            model=settings.ANSWER_FAST_MODEL or settings.LLM_MODEL,
            enable_thinking=settings.ANSWER_FAST_MODEL_THINKING,
            fallback_models=(), attempts_per_model=1, retry_delay_seconds=0,
        )
        self.fast_answer_llm = ObservedLLM(fast_model, "answer_generation_fast")
        self.answer_formatter = answer_formatter or AnswerFormatter()
        self.trace_service = TraceService()
        self.audit_service = audit_service or AuditService()
        self.memory_observability = memory_observability or MemoryObservability()
        self.fact_proposal_policy = fact_proposal_policy or FactProposalPolicy(observability=self.memory_observability)
        self.permission_service = permission_service or PermissionService()

        # Toolset owns registration; Agent only consumes it through an adapter.
        if toolset_registry is not None and tools is not None:
            raise ValueError("tools and toolset_registry cannot both be provided")
        toolset_registry = toolset_registry or ToolsetRegistry(tools=tools)
        self.registry = ToolRegistryAdapter(toolset_registry)
        if permission_service is None:
            read_tool = self.registry.get_tool("get_document")
            repository = getattr(read_tool, "repository", None)
            if repository is not None:
                self.permission_service.source_provider.documents_dir = repository.documents_dir
                self.permission_service.source_provider.document_loader = repository.load

        search_tool = self.registry.get_tool("search_documents")
        if isinstance(search_tool, SearchTool):
            search_tool.min_score = settings.MIN_RETRIEVAL_SCORE

        self.runner = runner or AgentRunner(llm=self.runtime_llm, registry=self.registry)
        self.tool_executor = tool_executor or ToolExecutor(self.registry)
        self.evidence_gate = evidence_gate or EvidenceGate()
        self.citation_checker = citation_checker or CitationChecker()
        self.memory_coordinator = memory_coordinator or MemoryCoordinator()
        self.orchestrator = orchestrator or ThinkingPipeline(
            memory_coordinator=self.memory_coordinator,
            runner=self.runner,
            tool_executor=self.tool_executor,
            evidence_gate=self.evidence_gate,
            citation_checker=self.citation_checker,
        )
        self.fast_pipeline = FastPipeline(
            llm=self.fast_answer_llm, executor=self.tool_executor,
            memory=self.memory_coordinator, citations=self.citation_checker,
        )
        self.thinking_pipeline = self.orchestrator
        # Compatibility diagnostics stay local to the current request context.
        self._last_run_result: ContextVar[AgentRunResult | None] = ContextVar(
            f"agent_last_run_result_{id(self)}",
            default=None,
        )
        self._last_orchestration: ContextVar[OrchestrationResult | None] = ContextVar(
            f"agent_last_orchestration_{id(self)}",
            default=None,
        )
        self._last_citation_check: ContextVar[Any | None] = ContextVar(
            f"agent_last_citation_check_{id(self)}",
            default=None,
        )

    @property
    def last_run_result(self) -> AgentRunResult | None:
        """Return diagnostics for this request context, for compatibility only."""
        return self._last_run_result.get()

    @last_run_result.setter
    def last_run_result(self, value: AgentRunResult | None) -> None:
        self._last_run_result.set(value)

    @property
    def last_orchestration(self) -> OrchestrationResult | None:
        """Return diagnostics for this request context, for compatibility only."""
        return self._last_orchestration.get()

    @last_orchestration.setter
    def last_orchestration(self, value: OrchestrationResult | None) -> None:
        self._last_orchestration.set(value)

    @property
    def last_citation_check(self) -> Any | None:
        """Return diagnostics for this request context, for compatibility only."""
        return self._last_citation_check.get()

    @last_citation_check.setter
    def last_citation_check(self, value: Any | None) -> None:
        self._last_citation_check.set(value)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Backward-compatible mapping used by CP1 callers."""
        return {tool.name: tool for tool in self.registry.get_all_tools()}

    def chat(
        self,
        request: ChatRequest,
        query_plan: QueryPlan | None = None,
    ) -> ChatResponse:
        """Execute one chat turn and preserve the CP1 Web response contract."""
        start_time = self.audit_service.start_timer()
        metrics_token = start_llm_metrics()
        trace_id = self.trace_service.start_trace()
        self.last_run_result = None
        self.last_orchestration = None
        self.last_citation_check = None
        persistent_memory_request = self._is_persistent_memory_request(request)
        guard = AccessGuard(self.permission_service, request, trace_id)
        guard_token = CURRENT_ACCESS_GUARD.set(guard)

        try:
            request = guard.sanitize_request()
            context = getattr(request, "attachment_context", None)
            for tool_name in ("search_attachments", "read_attachment_context"):
                tool = self.registry.get_tool(tool_name)
                if tool is not None and hasattr(tool, "set_request_context"):
                    tool.set_request_context(
                        context.allowed_attachment_ids if context else [],
                        context.selected_attachment_ids if context else [],
                    )
            library_context = getattr(request, "personal_library_context", None)
            library_tool = self.registry.get_tool("search_library")
            if library_tool is not None and hasattr(library_tool, "set_request_context"):
                library_tool.set_request_context(
                    library_context.owner_user_id if library_context else "",
                    library_context.knowledge_base_id if library_context else "",
                    library_context.access_token if library_context else "",
                )
            execution = self._chat_internal(request, trace_id, query_plan=query_plan)
            response = execution.response
            response.evidence_provenance = guard.provenance()
            latency_ms = self.audit_service.stop_timer(start_time)
            logger.debug("Agent request completed trace_id=%s latency_ms=%s", trace_id, latency_ms)
            return response
        except Exception as exc:
            latency_ms = self.audit_service.stop_timer(start_time)
            logger.debug("Agent request failed trace_id=%s latency_ms=%s", trace_id, latency_ms)
            raise exc
        finally:
            for name in ("search_library", "search_attachments", "read_attachment_context",
                         ):
                tool = self.registry.get_tool(name)
                if tool is not None and hasattr(tool, "clear_request_context"):
                    tool.clear_request_context()
            CURRENT_ACCESS_GUARD.reset(guard_token)
            clear_llm_metrics(metrics_token)
            self.trace_service.clear_trace()

    def _resolve_filters(self, request: ChatRequest) -> Optional[dict[str, Any]]:
        """Merge request filters with user permission isolation."""
        filters: dict[str, Any] = dict(request.filters) if request.filters else {}
        candidates = filters.get("doc_ids", filters.get("doc_id"))
        if isinstance(candidates, str):
            candidates = [candidates]
        accessible_doc_ids = self.permission_service.get_accessible_doc_ids_strict(request.user_id or "", doc_ids=candidates)

        accessible = set(accessible_doc_ids)
        existing = filters.get("doc_ids") if "doc_ids" in filters else filters.get("doc_id")
        if existing is not None:
            accessible &= {existing} if isinstance(existing, str) else set(existing)

        filters["doc_ids"] = sorted(accessible)
        return filters

    def _chat_internal(
        self,
        request: ChatRequest,
        trace_id: str,
        *,
        query_plan: QueryPlan | None = None,
    ) -> "AgentChatExecution":
        query = request.query.strip()
        if not query:
            return AgentChatExecution(self._error_response(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.INVALID_QUERY,
                message="请输入有效问题。",
                stage="validation",
                retrieval_mode=request.retrieval_mode,
                top_k=request.top_k,
            ))

        if self._propose_explicit_facts(request):
            return AgentChatExecution(ChatResponse(trace_id=trace_id, status=StatusCode.SUCCESS, answer="A session memory suggestion is ready. Please confirm it in the interface.", message="", citations=[]))

        if request.weight_mode in {None, "fast"}:
            turn = self.fast_pipeline.run(request, trace_id=trace_id, query_plan=query_plan)
            recalled = turn.memory.recall is not None and turn.memory.recall.handled
            self.last_run_result = None if recalled else turn.result
            turn.result.llm_metrics = snapshot_llm_metrics()
            orchestration = OrchestrationResult(
                query_plan=turn.plan,
                run_result=self.last_run_result, history=turn.memory.history_for_model(),
                retrieval_mode=request.retrieval_mode, top_k=request.top_k,
                context_artifact=turn.memory.context_artifact, memory_recall=turn.memory.recall if recalled else None,
                execution_profile=ExecutionProfile("fast", ExecutionMode.FAST, "off", "explicit_fast"),
            )
            self.last_orchestration = orchestration
            self._log_result(response=turn.response, query=request.query,
                retrieval_count=len(turn.result.evidence), stage="fast",
                retrieval_mode=request.retrieval_mode, top_k=request.top_k, error=turn.result.error_code)
            return AgentChatExecution(turn.response, orchestration)

        # Inject permission filters into request
        resolved_filters = self._resolve_filters(request)
        if resolved_filters:
            request = request.model_copy(update={"filters": resolved_filters})

        try:
            orchestration = self.thinking_pipeline.run(
                request,
                trace_id=trace_id,
                query_plan=query_plan,
            )

        except ValueError as exc:
            return AgentChatExecution(self._error_response(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.INVALID_QUERY,
                message="查询计划与当前请求不一致。",
                stage="query_plan_validation",
                retrieval_mode=request.retrieval_mode,
                top_k=request.top_k,
                error=str(exc),
            ))

        self.last_orchestration = orchestration
        plan = orchestration.query_plan
        run_result = orchestration.run_result
        self.last_run_result = run_result
        if orchestration.context_artifact is not None and not (orchestration.memory_recall is not None and orchestration.memory_recall.handled):
            self.memory_observability.prompt(model_history_chars=sum(len(m.content) for m in orchestration.context_artifact.model_history))

        memory_recall = orchestration.memory_recall
        if memory_recall is not None and memory_recall.handled:
            return AgentChatExecution(ChatResponse(
                trace_id=trace_id,
                status=StatusCode.SUCCESS,
                answer=memory_recall.answer or "",
                message="",
                citations=[],
            ), orchestration)

        if run_result is None:
            raise RuntimeError("orchestration returned no runtime result")

        response = self._map_run_result(
            run_result=run_result,
            trace_id=trace_id,
            query=request.query,
            retrieval_mode=orchestration.retrieval_mode,
            top_k=orchestration.top_k,
        )
        is_first = request.is_first_message
        if is_first is None:
            is_first = not any(
                message.get("role") != "system"
                for message in orchestration.history
            )

        if is_first:
            response.chat_title = " ".join(request.query.split())[:80]

        citation_check = self.orchestrator.validate_citations(
            response.answer,
            response.citations,
            run_result.evidence,
        )
        self.last_citation_check = citation_check
        if response.status == StatusCode.SUCCESS:
            if not citation_check.valid:
                response.status = StatusCode.QUALITY_VALIDATION_FAILED
                response.answer, response.citations = "", []
                response.message = "The answer failed citation validation."
            else:
                check_model_access()
                from agent.streaming.live import emit_model_event
                emit_model_event("token", {"content": response.answer})
        run_result.llm_metrics = snapshot_llm_metrics()
        logger.info(
            "[LLM_METRICS] trace_id=%s metrics=%s",
            trace_id,
            run_result.llm_metrics,
        )
        return AgentChatExecution(response, orchestration)

    @staticmethod
    def _is_persistent_memory_request(request: ChatRequest) -> bool:
        return settings.PERSISTENT_MEMORY_ENABLED and isinstance(
            request,
            InternalChatRequest,
        )

    def _audit_answer(self, response: ChatResponse) -> str:
        memory_recall = (
            self.last_orchestration.memory_recall
            if self.last_orchestration is not None
            else None
        )
        if memory_recall is not None and memory_recall.handled:
            return "[memory_recall]"
        return response.answer or response.message

    def _map_run_result(
        self,
        *,
        run_result: AgentRunResult,
        trace_id: str,
        query: str,
        retrieval_mode: str,
        top_k: int,
    ) -> ChatResponse:
        if run_result.stop_reason == StopReason.CLARIFICATION_REQUIRED:
            response = ChatResponse(
                trace_id=trace_id,
                status=StatusCode.CLARIFICATION_REQUIRED,
                answer="",
                message=run_result.message,
                citations=[],
            )
            self._log_result(
                response=response,
                query=query,
                stage="clarification",
                retrieval_mode=retrieval_mode,
                top_k=top_k,
                retrieval_count=0,
                error=run_result.error_code,
            )
            return response

        if run_result.stop_reason == StopReason.UNSUPPORTED:
            return self._error_response(
                trace_id=trace_id,
                query=query,
                status=StatusCode.UNSUPPORTED,
                message=run_result.message or "当前请求超出 Agent 的能力范围。",
                stage="policy",
                retrieval_mode=retrieval_mode,
                top_k=top_k,
                error=run_result.error_code,
            )

        retrieval_results = self._to_retrieval_results(run_result.evidence)
        if run_result.stop_reason == StopReason.FINAL_ANSWER:
            response = self.answer_formatter.format_success(
                trace_id=trace_id,
                answer=run_result.answer,
                retrieval_results=retrieval_results,
            )
            self._log_result(
                response=response,
                query=query,
                stage="completed",
                retrieval_mode=retrieval_mode,
                top_k=top_k,
                retrieval_count=len(retrieval_results),
            )
            return response

        status, message, stage = self._error_mapping(run_result)
        if not re.search(r"[\u4e00-\u9fff]", query):
            message = {
                StatusCode.NO_RELEVANT_CONTEXT: "I cannot confirm this from the authorized documents. Please provide the missing evidence or clarify the source scope.",
                StatusCode.LLM_ERROR: "The model service is temporarily unavailable. Please try again.",
                StatusCode.TOOL_ERROR: "A required tool is temporarily unavailable. Please try again.",
                StatusCode.RETRIEVAL_ERROR: "The retrieval service is temporarily unavailable. Please try again.",
                StatusCode.AGENT_LIMIT_REACHED: "The request reached its execution limit. Please narrow the question and try again.",
            }.get(status, message)
        return self._error_response(
            trace_id=trace_id,
            query=query,
            status=status,
            message=message,
            stage=stage,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            retrieval_count=len(retrieval_results),
            error=run_result.error_code,
        )

    @staticmethod
    def _error_mapping(
        run_result: AgentRunResult,
    ) -> tuple[StatusCode, str, str]:
        if run_result.stop_reason == StopReason.QUALITY_VALIDATION_FAILED:
            return StatusCode.QUALITY_VALIDATION_FAILED, "The answer did not pass source binding or MiniCheck verification within the execution budget.", "answer_grounding"
        if run_result.stop_reason == StopReason.NO_RELEVANT_CONTEXT:
            return (
                StatusCode.NO_RELEVANT_CONTEXT,
                run_result.message or "当前知识库没有足够信息回答该问题。",
                "quality_gate",
            )
        if run_result.stop_reason == StopReason.LLM_ERROR:
            return StatusCode.LLM_ERROR, "服务异常，请稍后重试。", "llm"
        if run_result.stop_reason == StopReason.TOOL_ERROR:
            if run_result.error_code == "retrieval_error":
                return (
                    StatusCode.RETRIEVAL_ERROR,
                    run_result.message or "检索服务暂时不可用，请稍后重试。",
                    "retrieval",
                )
            return (
                StatusCode.TOOL_ERROR,
                run_result.message or "工具执行失败，请稍后重试。",
                "tool",
            )
        if run_result.stop_reason == StopReason.POLICY_LIMIT:
            return (
                StatusCode.AGENT_LIMIT_REACHED,
                run_result.message or "The request reached its execution budget.",
                "policy",
            )
        return (
            StatusCode.AGENT_LIMIT_REACHED,
            run_result.message or "Agent 已安全停止。",
            "agent_limit",
        )

    @staticmethod
    def _to_retrieval_results(
        evidence: list[dict[str, Any]],
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        for item in evidence:
            try:
                result = RetrievalResult(
                    doc_id=str(item["doc_id"]),
                    chunk_id=canonical_chunk_id(str(item["doc_id"]), item.get("chunk_id"), item.get("chunk_index")),
                    chunk_index=int(item.get("chunk_index", 0)),
                    chunk_text=str(item.get("chunk_text", item.get("content", ""))),
                    title=str(item.get("title", "")),
                    source_url=item.get("source_url") or "",
                    score=float(item["score"]),
                    source_type=str(item.get("source_type") or "knowledge"),
                    attachment_id=item.get("attachment_id"),
                    evidence_id=item.get("evidence_id"),
                    locator=item.get("locator"),
                    version=item.get("version"),
                    source_scope=item.get("source_scope"),
                    knowledge_base_id=item.get("knowledge_base_id"),
                    document_id=item.get("document_id"),
                    version_id=item.get("version_id"),
                    evidence_ref=item.get("evidence_ref"),
                    content_hash=item.get("content_hash"),
                    normalized_content_hash=item.get("normalized_content_hash"),
                    source_content_hash=item.get("source_content_hash"),
                    source_version=item.get("source_version"),
                    read_status=item.get("read_status"),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("[EVIDENCE_DROPPED] malformed evidence: %r", item)
                continue
            if result.score >= settings.MIN_RETRIEVAL_SCORE:
                results.append(result)
        return results

    def _error_response(
        self,
        *,
        trace_id: str,
        query: str,
        status: StatusCode,
        message: str,
        stage: str,
        retrieval_mode: str,
        top_k: int,
        retrieval_count: int = 0,
        error: str = "",
    ) -> ChatResponse:
        response = ChatResponse(
            trace_id=trace_id,
            status=status,
            answer="",
            message=message,
            citations=[],
        )
        self._log_result(
            response=response,
            query=query,
            retrieval_count=retrieval_count,
            stage=stage,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            error=error,
        )
        return response

    def _log_result(
        self,
        *,
        response: ChatResponse,
        query: str,
        retrieval_count: int,
        stage: str,
        retrieval_mode: str,
        top_k: int,
        error: str = "",
    ) -> None:
        self.audit_service.log_result(
            trace_id=response.trace_id,
            query=query,
            retrieval_count=retrieval_count,
            status=response.status,
            stage=stage,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            error=error,
        )

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return persisted audit records (not ConversationMemory messages)."""
        return self.audit_service.store.get_records(limit)

    def stream_chat(self, request: ChatRequest):
        """Deliver checked model deltas without crossing worker ContextVars."""
        from agent.streaming.live import CURRENT_STREAM_SINK, threaded_events

        def produce(send):
            sink_token = CURRENT_STREAM_SINK.set(send)
            try:
                for name, value in self._guarded_stream_chat(request):
                    send(name, value)
            finally:
                CURRENT_STREAM_SINK.reset(sink_token)

        yield from threaded_events(produce)

    def _guarded_stream_chat(self, request: ChatRequest):
        """Use the same business pipeline as JSON; adapt only the delivery."""
        if "chat" in self.__dict__:
            yield from chat_response_events(self.chat(request))
            return
        decision = None
        if isinstance(request, InternalChatRequest):
            response, decision = self.chat_with_memory(request)
        else:
            response = self.chat(request)
        yield "source", {"evidence_provenance": response.evidence_provenance.model_dump()}
        yield "citations", [item.model_dump() for item in response.citations]
        content = response.answer or (response.message if response.status == StatusCode.CLARIFICATION_REQUIRED else "")
        if response.status == StatusCode.CLARIFICATION_REQUIRED:
            yield "token", {"content": content}
        yield "answer", {"content": content}
        yield "done", {"trace_id": response.trace_id, "status": response.status,
                       "citations_count": len(response.citations), "chat_title": response.chat_title,
                       "message": response.message,
                       "memory_decision": decision.model_dump() if decision is not None else None,
                       "evidence_provenance": response.evidence_provenance.model_dump()}

    def _propose_explicit_facts(self, request: ChatRequest) -> list[FactProposal]:
        """Parse one trusted explicit Fact command without invoking LLM/RAG."""
        if (
            not isinstance(request, InternalChatRequest)
            or not self._is_persistent_memory_request(request)
        ):
            return []

        try:
            context = request.memory_context
            return self.fact_proposal_policy.propose(
                request.query,
                actor_authenticated=context.actor.authenticated,
                current_message_id=context.current_message_id,
                persistent_memory_enabled=settings.PERSISTENT_MEMORY_ENABLED,
                session_fact_enabled=settings.SESSION_FACT_ENABLED,
            )
        except Exception:
            # Candidate generation is optional and must not expose user data in logs.
            self.memory_observability.fact(action="suppressed", outcome="failed")
            return []


    def chat_with_memory(self, request: InternalChatRequest, query_plan: QueryPlan | None = None) -> tuple[ChatResponse, MemoryDecision]:
        """Retain the strict infra Memory envelope while using the optimized Chat pipeline."""
        response = self.chat(request, query_plan=query_plan)
        orchestration = self.last_orchestration
        proposals = self._propose_explicit_facts(request) if response.status == StatusCode.SUCCESS else []
        if orchestration is not None and orchestration.memory_recall is not None and orchestration.memory_recall.handled:
            self.memory_observability.fact(action="recalled", outcome="success" if orchestration.memory_recall.answer else "empty")
        return response, MemoryDecision(
            context_artifact=orchestration.context_artifact if orchestration is not None else None,
            fact_proposals=proposals,
            recall=orchestration.memory_recall if orchestration is not None else None,
        )

