from agent.schemas.chat import ChatResponse, Citation
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult


class AnswerFormatter:
    def format_success(
        self,
        trace_id: str,
        answer: str,
        retrieval_results: list[RetrievalResult],
    ) -> ChatResponse:
        citations = [
            Citation(
                citation_id=index,
                title=result.title,
                source_url=result.source_url,
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                score=result.score,
                snippet=result.chunk_text[:120],
            )
            for index, result in enumerate(retrieval_results, start=1)
        ]
        return ChatResponse(
            trace_id=trace_id,
            status=StatusCode.SUCCESS,
            answer=answer,
            message="",
            citations=citations,
        )

