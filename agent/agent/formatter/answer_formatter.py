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
        safe_answer = self._normalize_answer_references(
            answer.strip(), len(retrieval_results)
        )
        referenced_ids = sorted(
            {int(value) for value in REFERENCE_PATTERN.findall(safe_answer)}
        )
        selected_results: list[RetrievalResult] = []
        id_mapping: dict[int, int] = {}
        for citation_id in referenced_ids:
            if 1 <= citation_id <= len(retrieval_results):
                id_mapping[citation_id] = len(selected_results) + 1
                selected_results.append(retrieval_results[citation_id - 1])

        if not selected_results and retrieval_results:
            selected_results = [retrieval_results[0]]
            id_mapping = {1: 1}

        if id_mapping:
            safe_answer = REFERENCE_PATTERN.sub(
                lambda match: (
                    f"[{id_mapping[int(match.group(1))]}]"
                    if int(match.group(1)) in id_mapping
                    else ""
                ),
                safe_answer,
            )

        citations = [
            Citation(
                citation_id=index,
                title=result.title,
                source_url=result.source_url,
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                score=result.score,
                snippet=result.chunk_text,
                source_type=("attachment" if result.attachment_id else ("personal" if result.source_scope == "personal" else "knowledge")),
                attachment_id=result.attachment_id,
                evidence_id=result.evidence_id,
                locator=result.locator,
                version=result.version,
                source_scope=result.source_scope,
                knowledge_base_id=result.knowledge_base_id,
                document_id=result.document_id,
                version_id=result.version_id,
            )
            for index, result in enumerate(selected_results, start=1)
        ]
        return ChatResponse(
            trace_id=trace_id,
            status=StatusCode.SUCCESS,
            answer=safe_answer,
            message="",
            citations=citations,
        )

    def _normalize_answer_references(self, answer: str, citations_count: int) -> str:
        if not answer:
            return answer
        if citations_count == 0:
            return REFERENCE_PATTERN.sub("", answer).strip()

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
        normalized = re.sub(r"[ \t]{2,}", " ", normalized).strip()

        if not has_valid_reference:
            normalized = f"{normalized} [1]".strip()

        return normalized
