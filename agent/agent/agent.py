import logging
from typing import Any

from agent.config.settings import settings
from agent.formatter.answer_formatter import AnswerFormatter
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.memory import ConversationMemory, get_default_memory
from agent.runtime import AgentRunResult, AgentRunner, StopReason
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.schemas.query_plan import QueryPlan
from agent.schemas.retrieval import RetrievalResult
from agent.service import AuditService, TraceService
from toolset.tool_layer import BaseTool, SearchTool, ToolRegistry


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
    ) -> None:
        self.llm = llm or LLMClient()
        self.answer_formatter = answer_formatter or AnswerFormatter()
        self.trace_service = TraceService()
        self.audit_service = AuditService()
        self.registry = ToolRegistry(tools=tools)
        self.memory = memory or get_default_memory()

        search_tool = self.registry.get_tool("search_documents")
        if isinstance(search_tool, SearchTool):
            search_tool.min_score = settings.MIN_RETRIEVAL_SCORE

        self.runner = runner or AgentRunner(
            llm=self.llm,
            registry=self.registry,
            audit_service=self.audit_service,
        )
        self.last_run_result: AgentRunResult | None = None

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
        trace_id = self.trace_service.start_trace()

        try:
            response = self._chat_internal(request, trace_id, query_plan=query_plan)
            latency_ms = self.audit_service.stop_timer(start_time)
            self.audit_service.record(
                trace_id=trace_id,
                query=request.query,
                answer=response.answer,
                status=response.status,
                latency_ms=latency_ms,
                session_id=request.session_id,
            )
            return response
        finally:
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
            plan = self._resolve_query_plan(request, query_plan)
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

        history = self._get_conversation_history(request.session_id)
        run_result = self.run_plan(
            plan,
            history=history,
            trace_id=trace_id,
            mode=request.retrieval_mode,
            top_k=request.top_k,
        )
        self.last_run_result = run_result

        response = self._map_run_result(
            run_result=run_result,
            trace_id=trace_id,
            query=request.query,
            retrieval_mode=request.retrieval_mode,
            top_k=request.top_k,
        )
        self._save_conversation_turn(
            session_id=request.session_id,
            query=plan.original_query,
            response=response,
        )
        return response

    def run_plan(
        self,
        query_plan: QueryPlan,
        *,
        history: list[dict[str, Any]] | None = None,
        trace_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        max_iterations: int | None = None,
    ) -> AgentRunResult:
        """Public CP2 Runner boundary consumed after Query Understanding."""
        return self.runner.run(
            query_plan,
            history=history,
            trace_id=trace_id,
            mode=mode,
            top_k=top_k,
            max_iterations=max_iterations,
        )

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

        retrieval_results = self._to_retrieval_results(run_result.evidence)
        if run_result.stop_reason == StopReason.FINAL_ANSWER:
            if run_result.retrieval_attempts and not retrieval_results:
                return self._error_response(
                    trace_id=trace_id,
                    query=query,
                    status=StatusCode.NO_RELEVANT_CONTEXT,
                    message="当前知识库没有足够信息回答该问题。",
                    stage="quality_gate",
                    retrieval_mode=retrieval_mode,
                    top_k=top_k,
                )
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
                    chunk_text=str(item["chunk_text"]),
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
