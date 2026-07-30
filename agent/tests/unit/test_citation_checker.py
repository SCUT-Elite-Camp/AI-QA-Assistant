import pytest

from agent.evidence import CitationChecker
from agent.schemas.chat import Citation
from agent.schemas.tool_execution import Evidence


pytestmark = pytest.mark.no_storage


def _evidence(doc_id: str, chunk_id: str) -> Evidence:
    return Evidence(
        doc_id=doc_id,
        chunk_id=chunk_id,
        title=f"Title {doc_id}",
        content="Evidence content",
        score=0.9,
        retrieval_query="query",
        retrieval_mode="hybrid",
    )


def _citation(citation_id: int, doc_id: str, chunk_id: str) -> Citation:
    return Citation(
        citation_id=citation_id,
        title=f"Title {doc_id}",
        doc_id=doc_id,
        chunk_id=chunk_id,
        score=0.9,
        snippet="Evidence content",
    )


def test_valid_citations_map_answer_to_evidence() -> None:
    result = CitationChecker().validate(
        "First claim [1]. Second claim [2].",
        [
            _citation(1, "doc-1", "chunk-1"),
            _citation(2, "doc-2", "chunk-2"),
        ],
        [
            _evidence("doc-1", "chunk-1"),
            _evidence("doc-2", "chunk-2"),
        ],
    )

    assert result.valid is True
    assert result.errors == []
    assert result.referenced_ids == [1, 2]


def test_repeated_answer_marker_is_allowed() -> None:
    result = CitationChecker().validate(
        "Claim [1], repeated support [1].",
        [_citation(1, "doc-1", "chunk-1")],
        [_evidence("doc-1", "chunk-1")],
    )

    assert result.valid is True
    assert result.referenced_ids == [1]


def test_missing_citation_for_answer_marker_is_rejected() -> None:
    result = CitationChecker().validate(
        "Unsupported marker [2].",
        [_citation(1, "doc-1", "chunk-1")],
        [_evidence("doc-1", "chunk-1")],
    )

    assert result.valid is False
    assert "answer_references_missing_citations:2" in result.errors


def test_unused_citation_is_rejected() -> None:
    result = CitationChecker().validate(
        "Only one source [1].",
        [
            _citation(1, "doc-1", "chunk-1"),
            _citation(2, "doc-2", "chunk-2"),
        ],
        [
            _evidence("doc-1", "chunk-1"),
            _evidence("doc-2", "chunk-2"),
        ],
    )

    assert result.valid is False
    assert "citations_not_referenced_in_answer:2" in result.errors


def test_duplicate_and_non_contiguous_ids_are_rejected() -> None:
    result = CitationChecker().validate(
        "Claim [1].",
        [
            _citation(1, "doc-1", "chunk-1"),
            _citation(1, "doc-2", "chunk-2"),
        ],
        [
            _evidence("doc-1", "chunk-1"),
            _evidence("doc-2", "chunk-2"),
        ],
    )

    assert result.valid is False
    assert "duplicate_citation_ids" in result.errors
    assert "citation_ids_not_contiguous" in result.errors


def test_citation_without_accepted_evidence_is_rejected() -> None:
    result = CitationChecker().validate(
        "Claim [1].",
        [_citation(1, "doc-x", "chunk-x")],
        [_evidence("doc-1", "chunk-1")],
    )

    assert result.valid is False
    assert "citation_not_backed_by_evidence:1" in result.errors


def test_no_answer_markers_and_no_citations_is_valid() -> None:
    result = CitationChecker().validate(
        "Hello!",
        [],
        [],
    )

    assert result.valid is True
