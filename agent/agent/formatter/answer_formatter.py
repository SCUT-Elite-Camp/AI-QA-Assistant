import re

from agent.schemas.chat import ChatResponse, Citation
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult

REFERENCE_PATTERN = re.compile(r"\[(\d+)\]")


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
        safe_answer = self._normalize_answer_references(answer.strip(), len(citations))
        return ChatResponse(
            trace_id=trace_id,
            status=StatusCode.SUCCESS,
            answer=safe_answer,
            message="",
            citations=citations,
        )

    def _normalize_answer_references(self, answer: str, citations_count: int) -> str:
        if not answer or citations_count == 0:
            return answer

        valid_ids = {str(index) for index in range(1, citations_count + 1)}
        has_valid_reference = False

        def replace_reference(match: re.Match[str]) -> str:
            nonlocal has_valid_reference
            citation_id = match.group(1)
            if citation_id in valid_ids:
                has_valid_reference = True
                return match.group(0)
            return ""

        normalized = REFERENCE_PATTERN.sub(replace_reference, answer)
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()

        if not has_valid_reference:
            normalized = f"{normalized} [1]".strip()

        return normalized
