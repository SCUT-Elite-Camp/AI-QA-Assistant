import json
from typing import List, Dict, Any, Optional

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.formatter.answer_formatter import AnswerFormatter
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult
from toolset.tool_layer import ToolRegistry, SearchTool, BaseTool
from agent.service import TraceService, AuditService


class Agent:
    """A unified Agent class implementing ReAct loop execution, auditing, and logging."""

    def __init__(
        self,
        llm: BaseLLM | None = None,
        tools: List[BaseTool] | None = None,
        answer_formatter: AnswerFormatter | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.answer_formatter = answer_formatter or AnswerFormatter()

        # Load auxiliary services
        self.trace_service = TraceService()
        self.audit_service = AuditService()

        # Load tools using ToolRegistry
        self.registry = ToolRegistry(tools=tools)

        # Inject min_score config into SearchTool
        search_tool = self.registry.get_tool("search_documents")
        if search_tool and isinstance(search_tool, SearchTool):
            search_tool.min_score = settings.MIN_RETRIEVAL_SCORE


        from agent.prompt.templates import SYSTEM_ROLE
        self.system_prompt = SYSTEM_ROLE


    @property
    def tools(self) -> Dict[str, BaseTool]:
        """Provides backward compatibility for callers accessing the tools dictionary."""
        return {t.name: t for t in self.registry.get_all_tools()}

    def chat(self, request: ChatRequest) -> ChatResponse:

        """Main entry point. Handles trace_id binding, latency profiling, and SQLite history saving."""
        start_time = self.audit_service.start_timer()
        trace_id = self.trace_service.start_trace()

        try:
            response = self._chat_internal(request, trace_id)

            # Record latency and write to SQLite history database
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

    def _chat_internal(self, request: ChatRequest, trace_id: str) -> ChatResponse:
        """Runs the ReAct loop and maps the outcome to ChatResponse."""
        query = request.query.strip()
        retrieval_mode = request.retrieval_mode
        filters = request.filters or None

        if not query:
            return self._error_response(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.INVALID_QUERY,
                message="请输入有效问题。",
                stage="validation",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k
            )

        try:
            # Clear previous tool results
            search_tool = self.registry.get_tool("search_documents")
            if search_tool and hasattr(search_tool, "latest_results"):
                search_tool.latest_results = []


            # Execute the ReAct loop
            answer = self.run(query, mode=retrieval_mode, top_k=request.top_k)

            # Extract retrieved chunks for citation mapping
            latest_results = []
            if search_tool and hasattr(search_tool, "latest_results"):
                latest_results = search_tool.latest_results

            retrieval_results = [
                RetrievalResult(
                    doc_id=r["doc_id"],
                    chunk_id=r["chunk_id"],
                    chunk_index=r["chunk_index"],
                    chunk_text=r["chunk_text"],
                    title=r["title"],
                    source_url=r["source_url"],
                    score=r["score"],
                    source_type=r.get("source_type"),
                    keywords=r.get("keywords"),
                    tags=r.get("tags"),
                )
                for r in latest_results
            ]
            # Safety gate: Filter out results below min_score
            retrieval_results = [
                r for r in retrieval_results
                if r.score is not None and r.score >= settings.MIN_RETRIEVAL_SCORE
            ]
        except Exception as exc:
            import logging
            logging.getLogger("agent-layer").exception(
                "[CHAT_ERROR] Exception occurred in agent_loop for query '%s': %s", query, exc
            )
            from agent.errors.exceptions import LLMError
            status_code = StatusCode.LLM_ERROR
            message = "服务异常，请稍后重试。"
            if not isinstance(exc, LLMError):
                status_code = StatusCode.RETRIEVAL_ERROR
                message = "检索服务暂时不可用，请稍后重试。"

            return self._error_response(
                trace_id=trace_id,
                query=query,
                status=status_code,
                message=message,
                stage="agent_loop",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k,
                error=exc.__class__.__name__
            )

        if not answer or not answer.strip():
            return self._error_response(
                trace_id=trace_id,
                query=query,
                status=StatusCode.LLM_ERROR,
                message="模型服务暂时不可用，请稍后重试。",
                stage="llm",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k
            )

        if not retrieval_results:
            return self._error_response(
                trace_id=trace_id,
                query=query,
                status=StatusCode.NO_RELEVANT_CONTEXT,
                message="当前知识库没有足够信息回答该问题。",
                stage="quality_gate",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k
            )

        response = self.answer_formatter.format_success(
            trace_id=trace_id,
            answer=answer,
            retrieval_results=retrieval_results,
        )
        self.audit_service.log_result(
            trace_id=trace_id,
            query=query,
            retrieval_count=len(retrieval_results),
            status=response.status,
            stage="completed",
            retrieval_mode=retrieval_mode,
            top_k=request.top_k,
        )
        return response

    def run(self, query: str, max_iterations: int = 5, mode: str = "hybrid", top_k: int = 5) -> str:
        """Executes the core RAG pipeline.

        1. Retrieve context using search_documents tool.
        2. Detect card/segment results → auto-select dual prompt format.
        3. Inject retrieved context into the prompt.
        4. Invoke the LLM to generate the final answer.
        """
        tool = self.registry.get_tool("search_documents")

        # Step 1: Execute retrieval to populate search results
        self.audit_service.log_step(0, query)
        if tool:
            self.audit_service.log_tool_call(tool.name, {"query": query, "mode": mode, "top_k": top_k})

            # 使用 agentic 模式时启用双路检索
            use_agentic = (mode == "agentic")
            context_text = tool.execute(
                query=query,
                mode=mode,
                top_k=top_k,
                backend="agentic" if use_agentic else "standard",
            )
        else:
            context_text = ""

        # Step 2: 构建 Prompt（自动检测双格式）
        from agent.prompt.prompt_builder import PromptBuilder
        builder = PromptBuilder()

        if tool and hasattr(tool, "latest_results"):
            results = tool.latest_results
            has_cards = any(
                r.get("source_type") == "card" for r in results
            )
            if has_cards:
                # ─── 双格式 Prompt：卡片 + 段落 ──────
                cards_context = self._assemble_context_by_type(
                    results, "card", builder
                )
                segments_context = self._assemble_context_by_type(
                    results, "segment", builder
                )
                prompt = builder.build_dual(
                    query=query,
                    cards_context=cards_context,
                    segments_context=segments_context,
                )
            else:
                prompt = builder.build(query=query, context=context_text)
        else:
            prompt = builder.build(query=query, context=context_text)

        messages = [
            {"role": "user", "content": prompt},
        ]

        self.audit_service.log_step(1, query)
        response = self.llm.chat(messages)
        return (response.get("content") or "").strip()

    @staticmethod
    def _assemble_context_by_type(
        results: list[dict],
        source_type: str,
        builder,
    ) -> str:
        """按 source_type 筛选结果并组装为上下文"""
        typed_results = [
            r for r in results
            if r.get("source_type") == source_type
        ]
        if not typed_results:
            # 如果指定类型没有结果，返回空（legacy 结果视为 segment）
            if source_type == "segment":
                typed_results = [
                    r for r in results
                    if r.get("source_type") not in ("card",)
                ]
            if not typed_results:
                return ""

        blocks = []
        idx = 1
        for r in typed_results:
            prefix = "K" if r.get("source_type") == "card" else "S"
            block = builder.build_context_for_result(
                index=idx,
                source_type=r.get("source_type", source_type),
                content=r.get("chunk_text", ""),
                doc_id=r.get("doc_id", ""),
                keywords=r.get("keywords"),
                tags=r.get("tags"),
                score=r.get("score", 0.0),
            )
            blocks.append(block)
            idx += 1

        return "\n\n".join(blocks)


    def _error_response(
        self,
        trace_id: str,
        query: str,
        status: StatusCode,
        message: str,
        stage: str,
        retrieval_mode: str,
        top_k: int,
        retrieval_count: int = 0,
        error: str = ""
    ) -> ChatResponse:
        response = ChatResponse(
            trace_id=trace_id,
            status=status,
            answer="",
            message=message,
            citations=[],
        )
        self.audit_service.log_result(
            trace_id=trace_id,
            query=query,
            retrieval_count=retrieval_count,
            status=status,
            stage=stage,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            error=error,
        )
        return response

    def get_history(self, limit: int = 50) -> list[dict]:
        """Retrieves audit logging history from SQLite store."""
        return self.audit_service.store.get_records(limit)
