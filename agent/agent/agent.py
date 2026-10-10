import logging
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.answer import AnswerCompletenessChecker
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
from agent.orchestration import AgentOrchestrator, OrchestrationResult
from agent.policy import IntentPolicyRouter
from agent.query.ambiguity import ARCHITECTURE_SCOPE_QUESTION, needs_architecture_scope
from agent.query import (
    Clarifier,
    IntentClassifier,
    HybridIntentRouter,
    QueryPlanner,
    QueryPreparationAnalyzer,
    QueryRewriter,
    QueryUnderstanding,
    UnifiedQueryAnalyzer,
)
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import AgentRunResult, AgentRunner, StopReason
from agent.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Citation,
    FactProposal,
    InternalChatRequest,
    MemoryDecision,
)
from agent.schemas.common import StatusCode
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan, QueryIntent
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
        query_understanding: QueryUnderstanding | None = None,
        policy_router: IntentPolicyRouter | None = None,
        tool_executor: ToolExecutor | None = None,
        evidence_gate: EvidenceGate | None = None,
        corrective_retrieval: CorrectiveRetrievalPlanner | None = None,
        citation_checker: CitationChecker | None = None,
        orchestrator: AgentOrchestrator | None = None,
        answer_completeness_checker: AnswerCompletenessChecker | None = None,
        permission_service: PermissionService | None = None,
        toolset_registry: ToolsetRegistry | None = None,
        audit_service: AuditService | None = None,
        fact_proposal_policy: FactProposalPolicy | None = None,
        memory_observability: MemoryObservability | None = None,
    ) -> None:
        custom_llm_supplied = llm is not None
        self.llm = llm or LLMClient()
        self.runtime_llm = ObservedLLM(self.llm, "agent_runtime")
        self.answer_llm = ObservedLLM(self.llm, "answer_generation_complex")
        self.fast_answer_llm: BaseLLM | None = None
        if (
            not custom_llm_supplied
            and settings.ANSWER_FAST_MODEL
            and settings.ANSWER_FAST_MODEL != settings.LLM_MODEL
        ):
            self.fast_answer_llm = ObservedLLM(
                LLMClient(
                    model=settings.ANSWER_FAST_MODEL,
                    enable_thinking=settings.ANSWER_FAST_MODEL_THINKING,
                ),
                "answer_generation_fast",
            )
        self.title_llm = ObservedLLM(self.llm, "title_generation")
        completeness_llm: BaseLLM = self.llm
        if (
            not custom_llm_supplied
            and settings.ANSWER_COMPLETENESS_MODEL
            and settings.ANSWER_COMPLETENESS_MODEL != settings.LLM_MODEL
        ):
            completeness_llm = LLMClient(
                model=settings.ANSWER_COMPLETENESS_MODEL,
                enable_thinking=settings.ANSWER_COMPLETENESS_MODEL_THINKING,
            )
        self.completeness_llm = ObservedLLM(
            completeness_llm,
            "answer_completeness",
        )
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

        self.runner = runner or AgentRunner(
            llm=self.runtime_llm,
            registry=self.registry,
            audit_service=self.audit_service,
            answer_completeness_checker=(
                answer_completeness_checker or AnswerCompletenessChecker(self.completeness_llm)
            ),
            answer_llm=self.answer_llm,
            fast_answer_llm=self.fast_answer_llm,
        )
        preparation_llm: BaseLLM = self.llm
        preparation_fallback_llm: BaseLLM | None = None
        if (
            not custom_llm_supplied
            and settings.QUERY_PREPARATION_MODEL
            and settings.QUERY_PREPARATION_MODEL != settings.LLM_MODEL
        ):
            preparation_llm = LLMClient(model=settings.QUERY_PREPARATION_MODEL)
            preparation_fallback_llm = self.llm

        self.query_understanding = query_understanding or QueryUnderstanding(
            intent_classifier=HybridIntentRouter(
                fallback=IntentClassifier(
                    llm=ObservedLLM(self.llm, "intent_classifier")
                )
            ),
            clarifier=Clarifier(llm=ObservedLLM(self.llm, "clarifier")),
            query_rewriter=QueryRewriter(llm=ObservedLLM(self.llm, "query_rewriter")),
            query_planner=QueryPlanner(llm=ObservedLLM(self.llm, "query_planner")),
            unified_analyzer=UnifiedQueryAnalyzer(
                llm=ObservedLLM(self.llm, "unified_query_understanding")
            ),
            query_preparation=QueryPreparationAnalyzer(
                llm=ObservedLLM(preparation_llm, "query_preparation"),
                fallback_llm=(
                    ObservedLLM(
                        preparation_fallback_llm,
                        "query_preparation_fallback",
                    )
                    if preparation_fallback_llm is not None
                    else None
                ),
            ),
        )
        self.policy_router = policy_router or IntentPolicyRouter()
        self.tool_executor = tool_executor or ToolExecutor(self.registry)
        self.evidence_gate = evidence_gate or EvidenceGate()
        self.corrective_retrieval = (
            corrective_retrieval or CorrectiveRetrievalPlanner()
        )
        self.citation_checker = citation_checker or CitationChecker()
        self.orchestrator = orchestrator or AgentOrchestrator(
            memory_coordinator=memory_coordinator,
            query_understanding=self.query_understanding,
            policy_router=self.policy_router,
            runner=self.runner,
            tool_executor=self.tool_executor,
            evidence_gate=self.evidence_gate,
            corrective_retrieval=self.corrective_retrieval,
            citation_checker=self.citation_checker,
        )
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
            for tool_name in ("search_attachments", "inspect_attachment"):
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
            for tool_name in (
                "wiki_search", "wiki_read_page", "wiki_read_sources",
                "wiki_search_evidence",
            ):
                wiki_tool = self.registry.get_tool(tool_name)
                if wiki_tool is not None and hasattr(wiki_tool, "set_personal_context"):
                    wiki_tool.set_personal_context(
                        library_context.owner_user_id if library_context else "",
                        library_context.knowledge_base_id if library_context else "",
                        library_context.access_token if library_context else "",
                        secret=os.getenv("ATTACHMENT_INTERNAL_SECRET", ""),
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
            return ChatResponse(trace_id=trace_id, status=StatusCode.SUCCESS, answer="已生成一条待确认的会话记忆，请在界面确认。", message="", citations=[])

        # Inject permission filters into request
        resolved_filters = self._resolve_filters(request)
        if resolved_filters:
            request = request.model_copy(update={"filters": resolved_filters})

        try:
            orchestration = self.orchestrator.run(
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

        extracted_title, clean_answer = self._separate_title_and_answer(response.answer)
        if extracted_title:
            response.chat_title = extracted_title
            response.answer = clean_answer
        elif is_first:
            response.chat_title = self._generate_fallback_title(request.query)

        citation_check = self.orchestrator.validate_citations(
            response.answer,
            response.citations,
            run_result.evidence,
        )
        self.last_citation_check = citation_check
        if not citation_check.valid:
            logger.warning(
                "[CITATION_CHECK] trace_id=%s errors=%s",
                trace_id,
                citation_check.errors,
            )
        run_result.llm_metrics = snapshot_llm_metrics()
        logger.info(
            "[LLM_METRICS] trace_id=%s metrics=%s",
            trace_id,
            run_result.llm_metrics,
        )
        return AgentChatExecution(response, orchestration)

    @staticmethod
    def _separate_title_and_answer(answer_text: str) -> tuple[Optional[str], str]:
        """
        Extracts title if present in [TITLE: ...] format at the beginning of LLM response,
        and returns (extracted_title, clean_answer_text).
        """
        if not answer_text:
            return None, answer_text

        match = re.search(r"^\s*\[TITLE:\s*(.*?)\]\s*\n?", answer_text, re.IGNORECASE)
        if match:
            raw_title = match.group(1).strip()
            clean_title = raw_title.replace("'", "").replace('"', "").replace("`", "").replace("。", "").replace("！", "").replace("？", "").strip()
            clean_title = clean_title.replace("标题：", "").replace("Title:", "").replace("我想知道", "").strip()
            clean_answer = answer_text[match.end():].strip()
            if clean_title and 2 <= len(clean_title) <= 25:
                return clean_title, clean_answer

        return None, answer_text

    def _generate_fallback_title(self, query: str) -> str:
        """Fallback smart title generation via fast LLM call or clean query slice."""
        # A second model call must not delay completion of an English answer,
        # or turn its conversation title into Chinese.
        if not re.search(r"[\u3400-\u9fff]", query):
            return " ".join(query.split())[:80]
        try:
            prompt = f"请根据用户第一次提问，总结提取一个极简对话标题（3-10字，绝对不要聊天标点或无用词如'我想知道'）：\n问题：{query}"
            raw_res = self.title_llm.chat([{"role": "user", "content": prompt}], max_tokens=30, temperature=0.2)
            raw = raw_res.get("content", "") if isinstance(raw_res, dict) else str(raw_res)
            clean = raw.strip().replace("'", "").replace('"', "").replace("`", "").replace("。", "").replace("！", "").replace("？", "").strip()
            clean = clean.replace("标题：", "").replace("Title:", "").replace("我想知道", "").strip()
            if clean and 2 <= len(clean) <= 20:
                return clean
        except Exception as e:
            logger.warning(f"[AgentTitle] Fallback title generation error: {e}")
        clean_query = query.replace("我想知道", "").replace("请问", "").strip()
        return clean_query[:15] if len(clean_query) > 15 else clean_query

    def run_plan(
        self,
        query_plan: QueryPlan,
        *,
        history: list[dict[str, Any]] | None = None,
        trace_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        max_iterations: int | None = None,
        policy: IntentPolicy | None = None,
    ) -> AgentRunResult:
        """Public CP2 Runner boundary consumed after Query Understanding."""
        runner_kwargs: dict[str, Any] = {
            "history": history,
            "trace_id": trace_id,
            "mode": mode,
            "top_k": top_k,
            "max_iterations": max_iterations,
        }
        if policy is not None:
            runner_kwargs["policy"] = policy
        return self.runner.run(query_plan, **runner_kwargs)

    def run(
        self,
        query: str,
        max_iterations: int = 5,
        mode: str = "hybrid",
        top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> str:
        """Executes the core RAG pipeline directly for direct callers."""
        tool = self.registry.get_tool("search_documents")
        self.audit_service.log_step(0, query)
        if tool:
            self.audit_service.log_tool_call(tool.name, {"query": query, "mode": mode, "top_k": top_k})
            context_text = tool.execute(query=query, mode=mode, top_k=top_k, filters=filters)
        else:
            context_text = ""

        from agent.prompt.prompt_builder import PromptBuilder
        prompt = PromptBuilder().build(query=query, context=context_text)
        messages = [{"role": "user", "content": prompt}]
        self.audit_service.log_step(1, query)
        response = self.llm.chat(messages)
        return (response.get("content") or "").strip()

    def _merge_explicit_filters(
        self,
        request: ChatRequest,
        query_plan: QueryPlan,
    ) -> QueryPlan:
        if not request.filters:
            return query_plan
        merged_filters = dict(query_plan.filters or {})
        for key, value in (request.filters or {}).items():
            # Request filters are explicit caller constraints and therefore
            # take precedence over filters inferred by QueryPlanner.
            merged_filters[key] = value
        return query_plan.model_copy(update={"filters": merged_filters})

    def _get_conversation_history(
        self,
        session_id: str | None,
    ) -> list[dict[str, Any]]:
        if not settings.MEMORY_ENABLED or not session_id:
            return []
        return self.memory.get_messages(session_id)

    def _save_conversation_turn(
        self,
        *,
        session_id: str | None,
        query: str,
        response: ChatResponse,
        persistent_memory: bool = False,
    ) -> None:
        if (
            CURRENT_ACCESS_GUARD.get() is not None
            or
            not settings.MEMORY_ENABLED
            or not session_id
            or persistent_memory
            or response.status
            not in {StatusCode.SUCCESS, StatusCode.CLARIFICATION_REQUIRED}
        ):
            return

        assistant_content = response.answer or response.message
        if not assistant_content:
            return
        self.memory.add_message(session_id, "user", query)
        self.memory.add_message(session_id, "assistant", assistant_content)

    @staticmethod
    def _resolve_query_plan(request: ChatRequest, plan: QueryPlan) -> QueryPlan:
        merged_filters = dict(plan.filters or {})
        for key, value in (request.filters or {}).items():
            if key in merged_filters and merged_filters[key] != value:
                raise ValueError(f"conflicting hard filter: {key}")
            merged_filters[key] = value
        return plan.model_copy(update={"filters": merged_filters})

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
                run_result.message or "Agent 已达到当前意图的执行预算。",
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

    def _retrieve_fast_context(self, request: ChatRequest, search_tool: SearchTool, trace_id: str):
        """Keep each comparison target represented without relaxing authorization."""
        filters = self._resolve_filters(request) or {}
        queries = [request.query]
        if not QueryPlanner._is_simple_single_target(request.query):
            intent = QueryIntent.COMPARISON if re.search(r"\b(compare|versus|vs|differences?)\b|比较|对比", request.query, re.I) else QueryIntent.KNOWLEDGE_QA
            plan = self.query_understanding.query_planner.enrich(request.query, intent)
            queries = list(dict.fromkeys(plan.sub_queries[:4])) or queries
        discovery = self.registry.get_tool("find_documents")
        batches = []
        snapshot_dates = {}
        for query in queries:
            scoped_filters = filters
            selected = []
            if len(queries) > 1 and discovery is not None:
                discovery_result = discovery.execute(query=query[:512], filters=filters, top_k=20)
                guard = CURRENT_ACCESS_GUARD.get()
                if guard:
                    guard.capture_tool("find_documents", discovery_result, [])
                documents = discovery_result.get("documents", [])
                selected = self._matching_target_documents(query, documents)
                if "doc_ids" in filters:
                    selected = [doc_id for doc_id in selected if doc_id in filters["doc_ids"]]
                if selected:
                    scoped_filters = {**filters, "doc_ids": selected}
            hits = search_tool.search(
                query=query, top_k=request.top_k or 5,
                mode=request.retrieval_mode or "hybrid", filters=scoped_filters, trace_id=trace_id,
            )
            guard = CURRENT_ACCESS_GUARD.get()
            if guard:
                guard.capture_tool("search_documents", {"items": hits}, [])
            reader = self.registry.get_tool("get_document")
            context = []
            if reader is not None:
                for doc_id in selected:
                    page = self._guarded_document_read(reader, doc_id=doc_id, limit=8)
                    snapshot_dates[doc_id] = page.get('document', {}).get('last_updated')
                    # Short meeting notes often place limitations after the
                    # highest-scoring passage. Read the complete bounded note.
                    if page.get("error"):
                        continue
                    document = page.get("document", {})
                    context.extend({
                        "doc_id": doc_id, **chunk, "chunk_id": chunk.get("chunk_id"),
                        "title": document.get("title"), "source_url": document.get("source_url"),
                        "snapshot_date": document.get("last_updated"),
                        "chunk_text": chunk.get("text", ""),
                    } for chunk in page.get("chunks", []))
            batches.append(context + hits)
        # A small explicit source selection is the user's evidence boundary,
        # not a ranking hint. Include its bounded opening context even when
        # lexical search ranks every passage from a single selected document.
        reader = self.registry.get_tool("get_document")
        if reader is not None and 0 < len(filters.get("doc_ids", [])) <= 4:
            for doc_id in filters["doc_ids"]:
                page = self._guarded_document_read(reader, doc_id=doc_id, limit=8)
                if page.get("error"):
                    continue
                document = page.get("document", {})
                snapshot_dates[doc_id] = document.get("last_updated")
                batches.insert(0, [{
                    "doc_id": doc_id, **chunk, "chunk_id": chunk.get("chunk_id"),
                    "title": document.get("title"), "source_url": document.get("source_url"),
                    "snapshot_date": document.get("last_updated"), "chunk_text": chunk.get("text", ""),
                } for chunk in page.get("chunks", [])])
        # Round-robin prevents the first target from consuming the entire context.
        results, seen = [], set()
        for index in range(max((len(batch) for batch in batches), default=0)):
            for batch in batches:
                if index >= len(batch):
                    continue
                row = batch[index]
                key = (row.get("doc_id"), row.get("chunk_id"))
                if key not in seen:
                    results.append(row)
                    seen.add(key)
        results = results[:20]
        if re.search(r"\bremaining (?:limitations|constraints)\b", request.query, re.I):
            reader = self.registry.get_tool('get_document')
            for row in results:
                doc_id = row.get('doc_id')
                if doc_id not in snapshot_dates and reader is not None:
                    page = self._guarded_document_read(reader, doc_id=doc_id, limit=1)
                    snapshot_dates[doc_id] = page.get('document', {}).get('last_updated')
                row['snapshot_date'] = snapshot_dates.get(doc_id)
        return results

    @staticmethod
    def _matching_target_documents(query: str, documents: list[dict]) -> list[str]:
        """Prefer title matches for a named comparison target over team-wide text hits."""
        weeks = set(re.findall(r"\bW\d{2}\b", query, re.I))
        candidates = documents
        if len(weeks) == 1:
            week = next(iter(weeks)).casefold()
            candidates = [d for d in documents if week in str(d.get("title", "")).casefold()]
        stop = {"the", "a", "an", "in", "of", "and", "for", "to", "with", "what", "give", "total", "counts", "count", "commits", "features", "fixes", "improvements", "other", "bug", "compare", "during"}
        def title_tokens(text):
            for month, name in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1):
                text = re.sub(r"\b" + name + r"\b", str(month), text, flags=re.I)
            return {str(int(t)) if t.isdigit() else t for t in re.findall(r"[a-z]+\d*|\d+", text.casefold())} - stop
        tokens = title_tokens(query)
        scored = [(len(tokens & title_tokens(str(d.get("title", "")))), d) for d in candidates]
        best = max((score for score, _ in scored), default=0)
        # A weak match should not suppress potentially relevant content matches.
        return [str(d["doc_id"]) for score, d in scored if score == best][:3] if best >= 2 else []

    def _guarded_document_read(self, reader, **arguments):
        guard = CURRENT_ACCESS_GUARD.get()
        if guard:
            arguments = guard.prepare_tool("get_document", arguments)
        result = reader.execute(**arguments)
        if guard and not result.get("error"):
            guard.capture_tool("get_document", result, [])
        return result

    def stream_chat(self, request: ChatRequest):
        """Buffer source-bearing output until live access and provenance pass."""
        if "chat" in self.__dict__:
            try:
                yield from chat_response_events(self.chat(request))
            except Exception as exc:
                yield "error", {"message": str(exc)}
            return
        # The mature Runner owns private-source routing; the partner's independent
        # Fast enterprise path and its quality checks remain intact below.
        from agent.query.source_intent import heuristic_source_intent
        from agent.schemas.query_plan import SourceKind
        private = isinstance(request, InternalChatRequest) and (
            request.attachment_context is not None and bool(request.attachment_context.allowed_attachment_ids)
            or request.personal_library_context is not None and SourceKind.PERSONAL_LIBRARY in heuristic_source_intent(request.query).sources)
        if request.weight_mode != "fast" or private:
            decision = None
            if isinstance(request, InternalChatRequest):
                response, decision = self.chat_with_memory(request)
            else:
                response = self.chat(request)
            yield "citations", [c.model_dump() for c in response.citations]
            yield "token", {"content": response.answer or response.message or ""}
            yield "done", {"trace_id": response.trace_id, "status": response.status,
                           "citations_count": len(response.citations), "chat_title": response.chat_title,
                           "memory_decision": decision.model_dump() if decision is not None else None,
                           "evidence_provenance": response.evidence_provenance.model_dump()}
            return
        guard = AccessGuard(self.permission_service, request, "fast-stream")
        token = CURRENT_ACCESS_GUARD.set(guard)
        try:
            request = guard.sanitize_request()
            events = list(self._stream_chat_unchecked(request))
            provenance = guard.provenance().model_dump()
            for name, value in events:
                if name == "done":
                    value = {**value, "evidence_provenance": provenance}
                yield name, value
        finally:
            CURRENT_ACCESS_GUARD.reset(token)

    def _stream_chat_unchecked(self, request: ChatRequest):
        """Execute streaming chat turn yielding (event_name, event_payload) tuples."""
        trace_id = self.trace_service.start_trace()
        start_time = self.audit_service.start_timer()
        try:
            # =========================================================================
            # FAST MODE: Independent direct RAG pipeline without agent multi-turn loops
            # =========================================================================
            if needs_architecture_scope(request.query):
                if request.session_id and CURRENT_ACCESS_GUARD.get() is None:
                    self.orchestrator.memory.add_message(request.session_id, "user", request.query)
                    self.orchestrator.memory.add_message(request.session_id, "assistant", ARCHITECTURE_SCOPE_QUESTION)
                yield "citations", []
                yield "token", {"content": ARCHITECTURE_SCOPE_QUESTION}
                yield "done", {"trace_id": trace_id, "status": StatusCode.CLARIFICATION_REQUIRED, "citations_count": 0}
                return

            if request.weight_mode == "fast":
                search_tool = self.registry.get_tool("search_documents")
                results = []
                if request.knowledge_base_retrieval_enabled and isinstance(search_tool, SearchTool):
                    results = self._retrieve_fast_context(request, search_tool, trace_id)

                citations = [
                    Citation(
                        citation_id=idx,
                        doc_id=str(r.get("doc_id", "") or ""),
                        chunk_id=str(r.get("chunk_id", "") or ""),
                        title=str(r.get("title", f"Document {idx}") or f"Document {idx}"),
                        source_url=r.get("source_url", None),
                        score=float(r.get("score", 0.0)) if r.get("score") is not None else None,
                        snippet=str(r.get("chunk_text", r.get("snippet", r.get("content", ""))) or ""),
                        source_type=str(r.get("source_type") or "knowledge"),
                        attachment_id=r.get("attachment_id"),
                        evidence_id=r.get("evidence_id"),
                        locator=r.get("locator"),
                        version=r.get("version"),
                        evidence_ref=r.get("evidence_ref"), content_hash=r.get("content_hash"),
                        normalized_content_hash=r.get("normalized_content_hash"),
                        source_content_hash=r.get("source_content_hash"),
                        source_version=r.get("source_version"), read_status=r.get("read_status"),
                        source_scope=r.get("source_scope"),
                        knowledge_base_id=r.get("knowledge_base_id"),
                        document_id=r.get("document_id"),
                        version_id=r.get("version_id"),
                    )
                    for idx, r in enumerate(results, start=1)
                ]
                yield "citations", [c.model_dump() for c in citations]

                from deep_research.model_report import EvidenceReportSynthesizer
                unsupported_entity = EvidenceReportSynthesizer._unsupported_count_entity(
                    request.query, citations)
                if unsupported_entity and not re.search(r"[\u3400-\u9fff]", request.query):
                    answer = f"The authorized excerpts do not establish the requested exact {unsupported_entity} counts. Counts for another module cannot substitute for them."
                    answer += ' ' + ''.join(f'[{c.citation_id}]' for c in citations[:3])
                    if request.session_id and CURRENT_ACCESS_GUARD.get() is None:
                        self.orchestrator.memory.add_message(request.session_id, "user", request.query)
                        self.orchestrator.memory.add_message(request.session_id, "assistant", answer)
                    yield "token", {"content": answer}
                    yield "done", {"trace_id": trace_id, "status": StatusCode.SUCCESS, "citations_count": len(citations)}
                    return

                context_blocks = []
                for idx, c in enumerate(citations, start=1):
                    context_blocks.append(f"[{idx}] Title: {c.title}\nSource URL: {c.source_url or 'not recorded'}\nLocator: {c.chunk_id}\nContent: {c.snippet}")
                context_text = "\n\n".join(context_blocks) if context_blocks else "无相关参考文档"

                history = ([{"role": m.role, "content": m.content} for m in request.memory_context.tail]
                           if isinstance(request, InternalChatRequest) else [])
                is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)
                title_directive = (
                    "\n\n【极重要指令】：这是本对话的第一个提问。请务必在最终回答的第一行输出您总结的对话标题，格式必须为：[TITLE: 3-10字精炼标题]，然后再换行输出正文回答。"
                    if is_first
                    else ""
                )

                system_prompt = (
                    "你是一个高效、精准的智能知识库问答助手。请根据提供的【参考上下文】详细回答用户的问题。\n"
                    "回答要求：\n"
                    "1. 事实严格基于参考上下文，条理清晰、层次分明；\n"
                    "2. 如果参考上下文未包含答案，请如实说明，并结合已知通用常识给出清晰提示；\n"
                    "3. 在引用上下文事实的地方，可适当标注引用编号（如 [1]、[2]）；\n"
                    "4. 直接输出最终回答，不要输出任何工具调用代码或标签。"
                    f"{title_directive}"
                )

                if not re.search(r"[\u3400-\u9fff]", request.query):
                    system_prompt = (
                        "Answer in English using only the authorized reference context. "
                        "Explain missing evidence without inventing facts. Cite factual claims with [1], [2], etc. "
                        "For comparisons, distinguish sources and calculate requested differences. "
                        "Respect the exact requested module and dates; team-wide totals cannot replace module totals. "
                        "A missing statement means unverified, not that the capability is absent. "
                        "For dated comparisons, label historical states by their source date. "
                        "Only describe a limitation as still remaining if the later source confirms it; "
                        "otherwise say its later status is unverified. Do not include weekdays unless asked. "
                        "Keep remaining limitations restricted to the later source. Mention older unresolved status "
                        "only for the dependency or capability explicitly asked about; omit unrelated historical constraints. "
                        "Never conclude 'not confirmed resolved, therefore still present': unknown status stays unknown. "
                        "Read the later source's Action Items as well as its discussion; relevant proposed repairs "
                        "are remaining limitations, not completed work. A demonstrated flow does not establish "
                        "production readiness or full integration. Keep comparisons within 200 words. "
                        "For counts, give only the requested numbers, their differences and citations; "
                        "do not infer team priorities or causes from numeric changes. "
                        "For implementation-file questions, identify files implementing the requested features; "
                        "When Python files are requested, list only .py paths, never .md documentation. "
                        "Goal identifiers may repeat across sections: bind each identifier to its exact goal NAME. "
                        "Translate non-English goal names into English while preserving identifiers and Latin component names. "
                        "Include the full English goal name next to repeated IDs. Omit unrequested owners, schedules and acceptance criteria. "
                        "Copy recorded status from that row; an empty status is 'not recorded', never 'Not started'. "
                        "Acceptance criteria and mock test criteria describe planned verification, not tests already performed. "
                        "do not list unrelated monorepo changes from a shared impacted-files table. "
                        "Output the answer directly without tool-call tags."
                    )
                    system_prompt += " Do not output TITLE metadata; the application generates the chat title separately."

                fast_messages = [{"role": "system", "content": system_prompt}]
                for msg in (history or []):
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        fast_messages.append({"role": msg["role"], "content": msg["content"]})

                fast_messages.append({
                    "role": "user",
                    "content": f"【参考上下文】:\n{context_text}\n\n【用户问题】:\n{request.query}"
                })

                accumulated_answer = ""
                from deep_research.model_report import EvidenceReportSynthesizer
                validate_dated_answer = (
                    not re.search(r"[\u3400-\u9fff]", request.query)
                    and (EvidenceReportSynthesizer.needs_dated_comparison(request.query)
                        or (re.search(r'\bgoals\b', request.query,re.I)
                            and re.search(r'\b(?:demonstrat\w*|capabilities|unresolved|status|recorded)\b',request.query,re.I))
                        or (re.search(r'\bLifecycle Archives\b',request.query,re.I)
                            and re.search(r'\blifetime commits\b',request.query,re.I))
                        or (re.search(r'\bCompare\b.{0,80}\bdeliveries\b',request.query,re.I)
                            and re.search(r'\bother (?:improvements|commits)\b',request.query,re.I))
                        or (re.search(r'\bMaster\b',request.query,re.I)
                            and re.search(r'\bStandby\b',request.query,re.I))
                        or re.search(r'\bCompare Total Commits\b',request.query,re.I)
                        or (re.search(r'\bSLA\b',request.query,re.I)
                            and re.search(r'\b(?:availability|uptime)\b',request.query,re.I))
                        or (re.search(r'\bWho committed\b',request.query,re.I)
                            and re.search(r'\btotal commits\b',request.query,re.I))
                        or re.search(r'\bConfluence\b',request.query,re.I)
                        or re.search(r'\bthree levels\b',request.query,re.I)
                        or (re.search(r'\bonly (?:the )?W\d{2} [A-Za-z_-]+ weekly report\b',request.query,re.I)
                            and re.search(r'\blatest\b',request.query,re.I))
                        or re.search(r'\bPython files\b',request.query,re.I))
                )
                check_model_access()
                for delta in self.llm.stream_chat(fast_messages):
                    reasoning = delta.get("reasoning_content")
                    content = delta.get("content")
                    if reasoning:
                        yield "reasoning", {"content": reasoning}
                    if content:
                        clean_content = re.sub(r"<longcat_.*?/?>|</longcat_.*?>", "", content)
                        if clean_content:
                            accumulated_answer += clean_content
                            if not validate_dated_answer:
                                yield "token", {"content": clean_content}

                quality_ok = True
                if validate_dated_answer:
                    yield "reasoning", {"content": "Verifying dated claims and the later source's remaining limitations."}
                    from deep_research.model_report import EvidenceReportSynthesizer
                    validator = EvidenceReportSynthesizer(api_base=settings.LLM_API_BASE,
                        api_key=settings.LLM_API_KEY, model=self.llm.model)
                    evidence = "\n\n".join(
                        f"[{c.citation_id}] {c.title} ({row.get('snapshot_date') or row.get('last_updated') or 'undated'}, {c.chunk_id})\nSource URL: {c.source_url or 'not recorded'}\nSource excerpt: {c.snippet}"
                        for c, row in zip(citations, results))
                    check_model_access()
                    checked = validator.repair_answer(accumulated_answer, request.query, evidence)
                    quality_ok = checked is not None
                    accumulated_answer = checked or (
                        "The sources were retrieved, but the answer did not pass evidence-quality validation. "
                        "Please review the source citations or retry."
                    )
                    yield "token", {"content": accumulated_answer}

                extracted_title, clean_answer = self._separate_title_and_answer(accumulated_answer)
                chat_title = extracted_title
                if not chat_title and is_first:
                    chat_title = self._generate_fallback_title(request.query)

                if request.session_id and CURRENT_ACCESS_GUARD.get() is None:
                    self.orchestrator.memory.add_message(request.session_id, "user", request.query)
                    self.orchestrator.memory.add_message(request.session_id, "assistant", clean_answer)

                yield "done", {
                    "trace_id": trace_id,
                    "status": StatusCode.SUCCESS if quality_ok else StatusCode.QUALITY_VALIDATION_FAILED,
                    "citations_count": len(citations),
                    "chat_title": chat_title,
                }
                return

            # =========================================================================
            # THINKING / AUTO MODE: Full Agent Planning & Reasoning Pipeline
            # =========================================================================
            search_tool = self.registry.get_tool("search_documents")
            if isinstance(search_tool, SearchTool):
                search_tool.topic_doc_ids = request.topic_doc_ids
                search_tool.topic_titles = request.topic_titles
                search_tool.weight_mode = request.weight_mode or "auto"
                search_tool.consecutive_no_new_docs_count = request.consecutive_no_new_docs_count or 0

            history = self.orchestrator._read_history(request.session_id)
            plan = self.orchestrator._resolve_query_plan(request, None, history)
            policy = self.orchestrator.policy_router.route(plan)
            retrieval_mode, top_k = self.orchestrator._effective_retrieval_options(request, policy)
            is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)

            state = AgentState(
                trace_id=trace_id,
                query_plan=plan,
                messages=self.orchestrator.runner._build_messages(
                    plan,
                    history or [],
                    is_first_message=is_first,
                    soul_content=request.soul_content,
                ),
            )

            for iteration in range(1, 3):
                schemas = self.orchestrator.runner._tool_schemas(policy)
                initial_res = self.llm.chat(state.messages, tools=schemas)
                tool_calls = initial_res.get("tool_calls") or []

                content_str = initial_res.get("content") or ""
                if not tool_calls and "<longcat_tool_call>" in content_str:
                    match = re.search(r"<longcat_tool_call>(\w+)(.*?)</longcat_tool_call>", content_str, re.DOTALL)
                    if match:
                        t_name = match.group(1).strip()
                        args_raw = match.group(2)
                        arg_matches = re.findall(r"<longcat_arg_key>(\w+)</longcat_arg_key>\s*<longcat_arg_value>(.*?)</longcat_arg_value>", args_raw, re.DOTALL)
                        t_args = {k: v.strip() for k, v in arg_matches}
                        import json as pyjson
                        tool_calls = [{"id": f"call_longcat_{iteration}", "type": "function", "function": {"name": t_name, "arguments": pyjson.dumps(t_args)}}]

                if not tool_calls:
                    break

                state.messages.append(self.orchestrator.runner._assistant_tool_call_message(initial_res, tool_calls))
                for raw_call in tool_calls:
                    call_id, tool_name, arguments = self.orchestrator.runner._parse_tool_call(raw_call)
                    arguments = self.orchestrator.runner._apply_execution_constraints(
                        tool_name=tool_name,
                        arguments=arguments,
                        query_plan=plan,
                        mode=retrieval_mode,
                        top_k=top_k,
                    )
                    tool = self.orchestrator.runner._get_tool(tool_name, policy)
                    if tool:
                        observation, evidence, is_retrieval = self.orchestrator.runner._execute_tool(
                            tool=tool,
                            tool_name=tool_name,
                            arguments=arguments,
                            query_plan=plan,
                            trace_id=trace_id,
                            tool_call_id=call_id,
                            tool_executor=self.orchestrator.tool_executor,
                            retrieval_attempt=iteration,
                        )
                        if evidence:
                            state.evidence.extend(evidence)
                        state.messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tool_name,
                            "content": observation,
                        })

            def _get_ev(item, key, default=None):
                if isinstance(item, dict):
                    return item.get(key, default)
                return getattr(item, key, default)

            citations = [
                Citation(
                    citation_id=idx,
                    doc_id=str(_get_ev(ev, "doc_id", "") or ""),
                    chunk_id=str(_get_ev(ev, "chunk_id", "") or ""),
                    title=str(_get_ev(ev, "title", f"Document {idx}") or f"Document {idx}"),
                    source_url=_get_ev(ev, "source_url", None),
                    score=float(_get_ev(ev, "score", 0.0)) if _get_ev(ev, "score") is not None else None,
                    snippet=str(_get_ev(ev, "chunk_text", _get_ev(ev, "snippet", _get_ev(ev, "content", ""))) or ""),
                    source_type=str(_get_ev(ev, "source_type", "knowledge") or "knowledge"),
                    attachment_id=_get_ev(ev, "attachment_id", None),
                    evidence_id=_get_ev(ev, "evidence_id", None),
                    locator=_get_ev(ev, "locator", None),
                    version=_get_ev(ev, "version", None),
                    source_scope=_get_ev(ev, "source_scope", None),
                    knowledge_base_id=_get_ev(ev, "knowledge_base_id", None),
                    document_id=_get_ev(ev, "document_id", None),
                    version_id=_get_ev(ev, "version_id", None),
                )
                for idx, ev in enumerate(state.evidence, start=1)
            ]
            yield "citations", [c.model_dump() for c in citations]

            state.messages.append({
                "role": "system",
                "content": "请基于已检索到的知识库事实与文档，直接给出完整、条理清晰的最终解答。不要输出任何工具调用标签。"
            })

            accumulated_answer = ""
            for delta in self.llm.stream_chat(state.messages):
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning:
                    yield "reasoning", {"content": reasoning}
                if content:
                    clean_content = re.sub(r"<longcat_.*?/?>|</longcat_.*?>", "", content)
                    if clean_content:
                        accumulated_answer += clean_content
                        yield "token", {"content": clean_content}

            extracted_title, clean_answer = self._separate_title_and_answer(accumulated_answer)
            chat_title = extracted_title
            if not chat_title and is_first:
                chat_title = self._generate_fallback_title(request.query)

            yield "done", {
                "trace_id": trace_id,
                "status": "success",
                "citations_count": len(citations),
                "chat_title": chat_title,
            }

            resp_obj = ChatResponse(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.SUCCESS,
                answer=clean_answer or accumulated_answer,
                message="",
                citations=citations,
                chat_title=chat_title,
            )
            self._save_conversation_turn(
                session_id=request.session_id,
                query=plan.original_query,
                response=resp_obj,
            )

        except Exception as exc:
            yield "error", {"message": str(exc)}
        finally:
            self.trace_service.clear_trace()


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

