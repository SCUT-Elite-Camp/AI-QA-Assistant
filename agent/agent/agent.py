import json
from typing import List, Dict, Any, Optional

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.formatter.answer_formatter import AnswerFormatter
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult
from toolset.tool_layer import get_tools, SearchTool, BaseTool
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

        # Load tools from Toolset layer if not passed
        self.tools = {t.name: t for t in (tools or get_tools())}

        # Inject min_score config into SearchTool
        search_tool = self.tools.get("search_documents")
        if search_tool and isinstance(search_tool, SearchTool):
            search_tool.min_score = settings.MIN_RETRIEVAL_SCORE

        from agent.prompt.templates import SYSTEM_ROLE
        self.system_prompt = SYSTEM_ROLE

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
            search_tool = self.tools.get("search_documents")
            if search_tool and hasattr(search_tool, "latest_results"):
                search_tool.latest_results = []

            # Execute the ReAct loop
            answer = self.run(query)

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
                    score=r["score"]
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

    def run(self, query: str, max_iterations: int = 1) -> str:
        """Executes the core ReAct loop steps."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": query})

        openai_tools = [t.to_openai_schema() for t in self.tools.values()]

        for i in range(max_iterations):
            # Call audit service to log step
            self.audit_service.log_step(i, query)

            response = self.llm.chat(messages, tools=openai_tools if openai_tools else None)

            tool_calls = response.get("tool_calls")
            if tool_calls:
                messages.append(response)
                for tc in tool_calls:
                    function_info = tc.get("function", {})
                    name = function_info.get("name")
                    arguments_str = function_info.get("arguments", "{}")

                    try:
                        args = json.loads(arguments_str) if arguments_str else {}
                    except Exception:
                        args = {}

                    tool = self.tools.get(name)
                    if tool:
                        self.audit_service.log_tool_call(name, args)
                        result = tool.execute(**args)
                    else:
                        result = f"Error: Tool {name} not found."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": name,
                        "content": str(result)
                    })
            else:
                return response.get("content") or ""

        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg.get("content")
        return "Agent execution exceeded maximum iterations without a final answer."

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
