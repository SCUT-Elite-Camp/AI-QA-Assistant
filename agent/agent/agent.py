import logging
from typing import Any, Optional

from agent.answer import AnswerCompletenessChecker
from agent.config.settings import settings
from agent.evidence import CitationChecker, EvidenceGate
from agent.formatter.answer_formatter import AnswerFormatter
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.llm.observability import (
    ObservedLLM,
    clear_llm_metrics,
    snapshot_llm_metrics,
    start_llm_metrics,
)
from agent.memory import ConversationMemory, get_default_memory
from agent.orchestration import AgentOrchestrator, OrchestrationResult
from agent.policy import IntentPolicyRouter
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
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.retrieval import RetrievalResult
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool, SearchTool
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry
from agent.service import AuditService, TraceService


logger = logging.getLogger("agent-layer")


class Agent:
    """Chat orchestrator for CP2 memory and bounded Agent execution."""

    def __init__(
        self,
        llm: BaseLLM | None = None,
        tools: list[BaseTool] | None = None,
        answer_formatter: AnswerFormatter | None = None,
        memory: ConversationMemory | None = None,
        runner: AgentRunner | None = None,
        query_understanding: QueryUnderstanding | None = None,
        policy_router: IntentPolicyRouter | None = None,
        tool_executor: ToolExecutor | None = None,
        evidence_gate: EvidenceGate | None = None,
        corrective_retrieval: CorrectiveRetrievalPlanner | None = None,
        citation_checker: CitationChecker | None = None,
        orchestrator: AgentOrchestrator | None = None,
        answer_completeness_checker: AnswerCompletenessChecker | None = None,
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
        self.audit_service = AuditService()
        # Toolset owns registration; Agent only consumes it through an adapter.
        toolset_registry = ToolsetRegistry(tools=tools)
        self.registry = ToolRegistryAdapter(toolset_registry)
        self.memory = memory or get_default_memory()

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
            memory=self.memory,
            query_understanding=self.query_understanding,
            policy_router=self.policy_router,
            runner=self.runner,
            tool_executor=self.tool_executor,
            evidence_gate=self.evidence_gate,
            corrective_retrieval=self.corrective_retrieval,
            citation_checker=self.citation_checker,
        )
        self.last_run_result: AgentRunResult | None = None
        self.last_orchestration: OrchestrationResult | None = None
        self.last_citation_check = None

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

        try:
            response = self._chat_internal(request, trace_id, query_plan=query_plan)
            latency_ms = self.audit_service.stop_timer(start_time)
            self.audit_service.record(
                trace_id=trace_id,
                query=request.query,
                answer=response.answer or response.message,
                status=response.status,
                latency_ms=latency_ms,
                session_id=request.session_id,
            )
            return response
        except Exception as exc:
            latency_ms = self.audit_service.stop_timer(start_time)
            self.audit_service.record(
                trace_id=trace_id,
                query=request.query,
                answer=f"Error: {exc}",
                status=StatusCode.AGENT_LIMIT_REACHED,
                latency_ms=latency_ms,
                session_id=request.session_id,
            )
            raise exc
        finally:
            clear_llm_metrics(metrics_token)
            self.trace_service.clear_trace()

    def _chat_internal(
        self,
        request: ChatRequest,
        trace_id: str,
        *,
        query_plan: QueryPlan | None = None,
    ) -> ChatResponse:
        query = request.query.strip()
        if not query:
            return self._error_response(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.INVALID_QUERY,
                message="请输入有效问题。",
                stage="validation",
                retrieval_mode=request.retrieval_mode,
                top_k=request.top_k,
            )

        try:
            search_tool = self.registry.get_tool("search_documents")
            if isinstance(search_tool, SearchTool):
                search_tool.topic_doc_ids = request.topic_doc_ids
                search_tool.topic_titles = request.topic_titles
                search_tool.weight_mode = request.weight_mode or "auto"
                search_tool.consecutive_no_new_docs_count = request.consecutive_no_new_docs_count or 0

            orchestration = self.orchestrator.run(
                request,
                trace_id=trace_id,
                query_plan=query_plan,
            )

        except ValueError as exc:
            return self._error_response(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.INVALID_QUERY,
                message="查询计划与当前请求不一致。",
                stage="query_plan_validation",
                retrieval_mode=request.retrieval_mode,
                top_k=request.top_k,
                error=str(exc),
            )

        self.last_orchestration = orchestration
        plan = orchestration.query_plan
        run_result = orchestration.run_result
        self.last_run_result = run_result

        response = self._map_run_result(
            run_result=run_result,
            trace_id=trace_id,
            query=request.query,
            retrieval_mode=orchestration.retrieval_mode,
            top_k=orchestration.top_k,
        )

        is_first = request.is_first_message
        if is_first is None:
            history_msgs = self.memory.get_messages(request.session_id) if request.session_id else []
            is_first = (len(history_msgs) == 0)

        extracted_title, clean_answer = self._separate_title_and_answer(response.answer)
        if extracted_title:
            response.chat_title = extracted_title
            response.answer = clean_answer
        elif is_first:
            response.chat_title = self._generate_fallback_title(request.query)

        self.last_citation_check = self.orchestrator.validate_citations(
            response.answer,
            response.citations,
            run_result.evidence,
        )
        if not self.last_citation_check.valid:
            logger.warning(
                "[CITATION_CHECK] trace_id=%s errors=%s",
                trace_id,
                self.last_citation_check.errors,
            )
        run_result.llm_metrics = snapshot_llm_metrics()
        logger.info(
            "[LLM_METRICS] trace_id=%s metrics=%s",
            trace_id,
            run_result.llm_metrics,
        )
        self._save_conversation_turn(
            session_id=request.session_id,
            query=plan.original_query,
            response=response,
        )
        return response

    @staticmethod
    def _separate_title_and_answer(answer_text: str) -> tuple[Optional[str], str]:
        """
        Extracts title if present in [TITLE: ...] format at the beginning of LLM response,
        and returns (extracted_title, clean_answer_text).
        """
        if not answer_text:
            return None, answer_text

        import re
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
            runner_kwargs.update(
                {
                    "policy": policy,
                    "tool_executor": self.tool_executor,
                    "evidence_gate": self.evidence_gate,
                    "corrective_retrieval": self.corrective_retrieval,
                }
            )
        return self.runner.run(query_plan, **runner_kwargs)

    def run(
        self,
        query: str | QueryPlan,
        max_iterations: int | None = None,
        mode: str = "hybrid",
        top_k: int = 5,
    ) -> str:
        """Backward-compatible text-only wrapper around the CP2 Runner."""
        plan = (
            query
            if isinstance(query, QueryPlan)
            else QueryPlan(
                original_query=query,
                standalone_query=query.strip(),
            )
        )
        trace_id = self.trace_service.start_trace()
        try:
            result = self.run_plan(
                plan,
                trace_id=trace_id,
                mode=mode,
                top_k=top_k,
                max_iterations=max_iterations,
            )
            self.last_run_result = result
            return result.answer
        finally:
            self.trace_service.clear_trace()

    @staticmethod
    def _resolve_query_plan(
        request: ChatRequest,
        query_plan: QueryPlan | None,
    ) -> QueryPlan:
        if query_plan is None:
            return QueryPlan(
                original_query=request.query,
                standalone_query=request.query.strip(),
                filters=dict(request.filters or {}),
            )

        if query_plan.original_query != request.query:
            raise ValueError("QueryPlan.original_query must exactly match ChatRequest.query")

        merged_filters = dict(query_plan.filters)
        for key, value in (request.filters or {}).items():
            if key in merged_filters and merged_filters[key] != value:
                raise ValueError(f"conflicting hard filter: {key}")
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
    ) -> None:
        if (
            not settings.MEMORY_ENABLED
            or not session_id
            or response.status
            not in {StatusCode.SUCCESS, StatusCode.CLARIFICATION_REQUIRED}
        ):
            return

        assistant_content = response.answer or response.message
        if not assistant_content:
            return
        self.memory.add_message(session_id, "user", query)
        self.memory.add_message(session_id, "assistant", assistant_content)

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
                    chunk_id=str(item["chunk_id"]),
                    chunk_index=int(item.get("chunk_index", 0)),
                    chunk_text=str(item.get("chunk_text", item.get("content", ""))),
                    title=str(item.get("title", "")),
                    source_url=item.get("source_url") or "",
                    score=float(item["score"]),
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
