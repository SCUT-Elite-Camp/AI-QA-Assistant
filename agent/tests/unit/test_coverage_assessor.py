from __future__ import annotations

import pytest

from agent.exploration import CoverageAssessor
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.schemas.tool_execution import Evidence


pytestmark = pytest.mark.no_storage


def _evidence(
    chunk_id: str,
    *,
    doc_id: str = "doc-1",
    chunk_index: int = 0,
    section_id: str = "",
    content: str | None = None,
) -> Evidence:
    return Evidence(
        doc_id=doc_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        title=doc_id,
        content=content or f"evidence {chunk_id}",
        score=0.8,
        retrieval_query="Agent 层完成了什么工作？",
        retrieval_mode="hybrid",
        locator={"section_id": section_id} if section_id else {},
    )


def _plan(**updates) -> QueryPlan:
    values = {
        "original_query": "Agent 层完成了什么工作？",
        "standalone_query": "Agent 层完成了什么工作？",
        "intent": QueryIntent.KNOWLEDGE_QA,
    }
    values.update(updates)
    return QueryPlan(**values)


def test_five_nearby_chunks_are_not_mistaken_for_complete_topic_coverage() -> None:
    assessment = CoverageAssessor().assess(
        _plan(),
        [_evidence(f"c{i}", chunk_index=i) for i in range(5)],
        available_actions=["wiki_search", "wiki_search_evidence"],
    )

    assert assessment.complex_query is True
    assert assessment.sufficient is False
    assert assessment.should_explore is True
    assert "topic_coverage" in assessment.missing_facets
    assert assessment.recommended_actions == ["wiki_search"]


def test_distinct_sections_satisfy_a_broad_single_document_question() -> None:
    assessment = CoverageAssessor().assess(
        _plan(),
        [
            _evidence("c1", section_id="sec-planning"),
            _evidence("c2", section_id="sec-tools"),
            _evidence("c3", section_id="sec-memory"),
        ],
        available_actions=["wiki_search", "wiki_search_evidence"],
    )

    assert assessment.sufficient is True
    assert assessment.should_explore is False
    assert assessment.unique_sections == 3


def test_multi_document_gap_recommends_wiki_search() -> None:
    assessment = CoverageAssessor().assess(
        _plan(intent=QueryIntent.COMPARISON),
        [_evidence("c1"), _evidence("c2", chunk_index=4)],
        available_actions=["wiki_search", "wiki_search_evidence"],
    )

    assert "cross_document_coverage" in assessment.missing_facets
    assert assessment.recommended_actions[0] == "wiki_search"


def test_exploration_off_never_recommends_a_tool() -> None:
    assessment = CoverageAssessor().assess(
        _plan(),
        [_evidence("c1")],
        exploration_mode="off",
        available_actions=["wiki_search", "wiki_search_evidence"],
    )

    assert assessment.sufficient is False
    assert assessment.should_explore is False
    assert assessment.recommended_actions == []


def test_duplicate_content_does_not_inflate_coverage() -> None:
    assessment = CoverageAssessor().assess(
        _plan(),
        [
            _evidence("c1", content="same content"),
            _evidence("c2", content=" same   content "),
            _evidence("c3", content="different"),
        ],
        available_actions=["wiki_search", "wiki_search_evidence"],
    )

    assert assessment.unique_evidence == 2
    assert "evidence_breadth" in assessment.missing_facets
