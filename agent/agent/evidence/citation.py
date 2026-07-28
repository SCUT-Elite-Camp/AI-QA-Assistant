import re

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.chat import Citation
from agent.schemas.tool_execution import Evidence


class CitationCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    referenced_ids: list[int] = Field(default_factory=list)


class CitationChecker:
    """Validate answer markers and Citation-to-Evidence identity."""

    _MARKER = re.compile(r"\[(\d+)\]")

    def validate(
        self,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
    ) -> CitationCheckResult:
        errors: list[str] = []
        referenced_ids = sorted(
            {int(value) for value in self._MARKER.findall(answer)}
        )
        citation_ids = [citation.citation_id for citation in citations]

        if len(citation_ids) != len(set(citation_ids)):
            errors.append("duplicate_citation_ids")

        expected_ids = list(range(1, len(citations) + 1))
        if sorted(citation_ids) != expected_ids:
            errors.append("citation_ids_not_contiguous")

        citation_id_set = set(citation_ids)
        missing_citations = sorted(set(referenced_ids) - citation_id_set)
        if missing_citations:
            errors.append(
                "answer_references_missing_citations:"
                + ",".join(map(str, missing_citations))
            )

        unused_citations = sorted(citation_id_set - set(referenced_ids))
        if unused_citations:
            errors.append(
                "citations_not_referenced_in_answer:"
                + ",".join(map(str, unused_citations))
            )

        evidence_keys = {
            (item.doc_id, item.chunk_id)
            for item in evidence
        }
        for citation in citations:
            if (citation.doc_id, citation.chunk_id) not in evidence_keys:
                errors.append(
                    f"citation_not_backed_by_evidence:{citation.citation_id}"
                )

        return CitationCheckResult(
            valid=not errors,
            errors=errors,
            referenced_ids=referenced_ids,
        )
