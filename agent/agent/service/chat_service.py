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
from agent.trace.trace_id import generate_trace_id


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

    def chat(self, request: ChatRequest) -> ChatResponse:
        trace_id = generate_trace_id()
        query = request.query.strip()
        retrieval_mode = request.retrieval_mode

        if not query:
            response = ChatResponse(
                trace_id=trace_id,
                status=StatusCode.INVALID_QUERY,
                answer="",
                message="请输入有效问题。",
                citations=[],
            )
            log_chat_result(trace_id, request.query, 0, response.status, stage="validation")
            return response

        # Q1 keeps stream as an interface placeholder; /api/chat always returns JSON.
        filters = request.filters or None

        try:
            retrieval_results = self.retriever.retrieve(
                query=query,
                top_k=request.top_k,
                filters=filters,
                mode=retrieval_mode,
                min_score=settings.MIN_RETRIEVAL_SCORE,
                trace_id=trace_id,
            )
            retrieval_results = self._filter_relevant_results(retrieval_results)
        except Exception as exc:
            response = ChatResponse(
                trace_id=trace_id,
                status=StatusCode.RETRIEVAL_ERROR,
                answer="",
                message="检索服务暂时不可用，请稍后重试。",
                citations=[],
            )
            log_chat_result(
                trace_id,
                query,
                0,
                response.status,
                stage="retrieval",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k,
                error=exc.__class__.__name__,
            )
            return response

        if not retrieval_results:
            response = ChatResponse(
                trace_id=trace_id,
                status=StatusCode.NO_RELEVANT_CONTEXT,
                answer="",
                message="当前知识库没有足够信息回答该问题。",
                citations=[],
            )
            log_chat_result(
                trace_id,
                query,
                0,
                response.status,
                stage="quality_gate",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k,
            )
            return response

        context = self.context_assembler.assemble(retrieval_results)
        prompt = self.prompt_builder.build(query=query, context=context)

        try:
            answer = self.llm.generate(prompt)
            if not answer or not answer.strip():
                raise ValueError("empty llm answer")
        except Exception as exc:
            response = ChatResponse(
                trace_id=trace_id,
                status=StatusCode.LLM_ERROR,
                answer="",
                message="模型服务暂时不可用，请稍后重试。",
                citations=[],
            )
            log_chat_result(
                trace_id,
                query,
                len(retrieval_results),
                response.status,
                stage="llm",
                retrieval_mode=retrieval_mode,
                top_k=request.top_k,
                error=exc.__class__.__name__,
            )
            return response

        response = self.answer_formatter.format_success(
            trace_id=trace_id,
            answer=answer,
            retrieval_results=retrieval_results,
        )
        log_chat_result(
            trace_id,
            query,
            len(retrieval_results),
            response.status,
            stage="completed",
            retrieval_mode=retrieval_mode,
            top_k=request.top_k,
        )
        return response

    def _filter_relevant_results(self, retrieval_results):
        return [
            result
            for result in retrieval_results
            if result.score is not None and result.score >= settings.MIN_RETRIEVAL_SCORE
        ]
