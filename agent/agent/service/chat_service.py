from agent.formatter.answer_formatter import AnswerFormatter
from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.llm.mock_llm import MockLLM
from agent.logger.app_logger import log_chat_result
from agent.prompt.context_assembler import ContextAssembler
from agent.prompt.prompt_builder import PromptBuilder
from agent.retrieval.base import BaseRetriever
from agent.retrieval.retrieval_adapter import RetrievalAdapter
from agent.schemas.chat import ChatRequest, ChatResponse
from agent.schemas.common import StatusCode
from agent.trace.trace_id import generate_trace_id, set_trace_id, clear_trace_id


class ChatService:
    def __init__(
        self,
        retriever: BaseRetriever | None = None,
        llm: BaseLLM | None = None,
        context_assembler: ContextAssembler | None = None,
        prompt_builder: PromptBuilder | None = None,
        answer_formatter: AnswerFormatter | None = None,
    ) -> None:
        self.retriever = retriever or RetrievalAdapter()
        self.llm = llm or (MockLLM() if settings.USE_MOCK_LLM else LLMClient())
        self.context_assembler = context_assembler or ContextAssembler()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.answer_formatter = answer_formatter or AnswerFormatter()

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
        trace_id = generate_trace_id()
        set_trace_id(trace_id)

        try:
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
                retrieval_results = self.retriever.retrieve(
                    query=query,
                    top_k=request.top_k,
                    filters=filters,
                    mode=retrieval_mode,
                    min_score=settings.MIN_RETRIEVAL_SCORE,
                    trace_id=trace_id,
                )
                retrieval_results = [
                    r for r in retrieval_results
                    if r.score is not None and r.score >= settings.MIN_RETRIEVAL_SCORE
                ]
            except Exception as exc:
                return self._error_response(
                    trace_id=trace_id,
                    query=query,
                    status=StatusCode.RETRIEVAL_ERROR,
                    message="检索服务暂时不可用，请稍后重试。",
                    stage="retrieval",
                    retrieval_mode=retrieval_mode,
                    top_k=request.top_k,
                    error=exc.__class__.__name__
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

            context = self.context_assembler.assemble(retrieval_results)
            prompt = self.prompt_builder.build(query=query, context=context)

            try:
                answer = self.llm.generate(prompt)
                if not answer or not answer.strip():
                    raise ValueError("empty llm answer")
            except Exception as exc:
                return self._error_response(
                    trace_id=trace_id,
                    query=query,
                    status=StatusCode.LLM_ERROR,
                    message="模型服务暂时不可用，请稍后重试。",
                    stage="llm",
                    retrieval_mode=retrieval_mode,
                    top_k=request.top_k,
                    retrieval_count=len(retrieval_results),
                    error=exc.__class__.__name__
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
        finally:
            clear_trace_id()
