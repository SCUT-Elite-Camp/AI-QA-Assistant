import time
from agent.formatter.answer_formatter import AnswerFormatter
from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.logger.app_logger import log_chat_result
from agent.prompt.context_assembler import ContextAssembler
from agent.prompt.prompt_builder import PromptBuilder
from agent.retrieval.base import BaseRetriever
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult
from agent.trace.trace_id import generate_trace_id, set_trace_id, clear_trace_id
from storage.chat_history_store import ChatHistoryStore


class ChatService:
    def __init__(
        self,
        retriever: BaseRetriever | None = None,
        llm: BaseLLM | None = None,
        context_assembler: ContextAssembler | None = None,
        prompt_builder: PromptBuilder | None = None,
        answer_formatter: AnswerFormatter | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.context_assembler = context_assembler or ContextAssembler()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.answer_formatter = answer_formatter or AnswerFormatter()

        # Expose tools from Toolset layer
        from toolset.tool_layer import get_tools, SearchTool
        self.tools = get_tools()

        # Inject min_score from settings to SearchTool
        for t in self.tools:
            if isinstance(t, SearchTool):
                t.min_score = settings.MIN_RETRIEVAL_SCORE

        # If a custom retriever is passed (e.g. in unit tests), override SearchTool's search behavior
        if retriever is not None:
            for t in self.tools:
                if isinstance(t, SearchTool):
                    def mock_search(query, top_k=5, mode="hybrid", filters=None):
                        results = retriever.retrieve(query, top_k=top_k, mode=mode, filters=filters)
                        return [
                            {
                                "doc_id": r.doc_id,
                                "chunk_id": r.chunk_id,
                                "chunk_index": r.chunk_index,
                                "chunk_text": r.chunk_text,
                                "title": r.title,
                                "source_url": r.source_url,
                                "score": r.score
                            }
                            for r in results
                        ]
                    t.search = mock_search

        from agent.prompt.templates import SYSTEM_ROLE
        from agent.service.agent import Agent
        self.agent = Agent(self.llm, self.tools, system_prompt=SYSTEM_ROLE)

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
        log_chat_result(
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

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Main chat entry point. Coordinates logging, latency tracing, and audit log persistence."""
        start_time = time.perf_counter()
        trace_id = generate_trace_id()
        set_trace_id(trace_id)

        try:
            response = self._chat_internal(request, trace_id)

            # Record request latency and persist log to SQLite chat history database
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            try:
                store = ChatHistoryStore()
                store.add_record(
                    trace_id=trace_id,
                    user_query=request.query,
                    assistant_answer=response.answer,
                    status=response.status,
                    latency_ms=latency_ms,
                    session_id=request.session_id,
                )
            except Exception:
                # Log database errors safely using a fallback
                pass

            return response
        finally:
            clear_trace_id()

    def _chat_internal(self, request: ChatRequest, trace_id: str) -> ChatResponse:
        """Executes actual query-response workflow including retrieval and model invocation."""
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
            # Run the Agent loop
            search_tool = self.agent.tools.get("search_documents")
            if search_tool and hasattr(search_tool, "latest_results"):
                search_tool.latest_results = []

            answer = self.agent.run(query)

            # Retrieve execution results from search tool
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
            retrieval_results = [
                r for r in retrieval_results
                if r.score is not None and r.score >= settings.MIN_RETRIEVAL_SCORE
            ]
        except Exception as exc:
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
        log_chat_result(
            trace_id=trace_id,
            query=query,
            retrieval_count=len(retrieval_results),
            status=response.status,
            stage="completed",
            retrieval_mode=retrieval_mode,
            top_k=request.top_k,
        )
        return response

    def get_history(self, limit: int = 50) -> list[dict]:
        """Retrieves history from database store."""
        try:
            store = ChatHistoryStore()
            return store.get_records(limit)
        except Exception:
            return []
