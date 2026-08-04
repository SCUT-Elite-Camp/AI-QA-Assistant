import pytest

from agent.evidence import EvidenceGate
from agent.policy import IntentPolicyRouter
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.schemas.tool_execution import Evidence


pytestmark = pytest.mark.no_storage


def _plan(
    intent: QueryIntent,
    *,
    sub_queries: list[str] | None = None,
) -> QueryPlan:
    return QueryPlan(
        original_query="test",
        standalone_query="test",
        intent=intent,
        sub_queries=sub_queries or [],
    )


def _evidence(
    *,
    doc_id: str = "doc-1",
    chunk_id: str = "chunk-1",
    score: float = 0.8,
    retrieval_query: str = "test",
) -> Evidence:
    return Evidence(
        doc_id=doc_id,
        chunk_id=chunk_id,
        title="Title",
        content="Evidence content",
        score=score,
        retrieval_query=retrieval_query,
        retrieval_mode="hybrid",
    )


def _evaluate(
    intent: QueryIntent,
    evidence: list[Evidence],
    *,
    attempt: int = 1,
    sub_queries: list[str] | None = None,
    min_score: float = 0.5,
):
    plan = _plan(intent, sub_queries=sub_queries)
    policy = IntentPolicyRouter().route(plan)
    return EvidenceGate(min_score=min_score).evaluate(
        plan,
        policy,
        evidence,
        retrieval_attempt=attempt,
    )


def test_knowledge_qa_accepts_one_valid_evidence() -> None:
    result = _evaluate(QueryIntent.KNOWLEDGE_QA, [_evidence()])

    assert result.accepted is True
    assert len(result.evidence) == 1
    assert result.should_retry is False


def test_low_score_evidence_is_rejected() -> None:
    result = _evaluate(
        QueryIntent.KNOWLEDGE_QA,
        [_evidence(score=0.49)],
    )

    assert result.accepted is False
    assert result.evidence == []
    assert result.reason == "no_valid_evidence"
    assert result.should_retry is True


def test_duplicate_chunks_keep_the_highest_score() -> None:
    result = _evaluate(
        QueryIntent.KNOWLEDGE_QA,
        [_evidence(score=0.7), _evidence(score=0.9)],
    )

    assert result.accepted is True
    assert [item.score for item in result.evidence] == [0.9]


def test_summarization_requires_multiple_valid_chunks() -> None:
    insufficient = _evaluate(
        QueryIntent.SUMMARIZATION,
        [_evidence()],
    )
    sufficient = _evaluate(
        QueryIntent.SUMMARIZATION,
        [
            _evidence(chunk_id="chunk-1"),
            _evidence(chunk_id="chunk-2", score=0.7),
        ],
    )

    assert insufficient.accepted is False
    assert insufficient.reason == "topic_coverage_insufficient"
    assert sufficient.accepted is True


def test_comparison_requires_evidence_for_each_sub_query() -> None:
    sub_queries = ["Agent CP1", "Agent CP2"]
    result = _evaluate(
        QueryIntent.COMPARISON,
        [_evidence(retrieval_query="Agent CP1")],
        sub_queries=sub_queries,
    )

    assert result.accepted is False
    assert result.missing_targets == ["Agent CP2"]
    assert result.should_retry is True


def test_comparison_accepts_bilateral_coverage() -> None:
    sub_queries = ["Agent CP1", "Agent CP2"]
    result = _evaluate(
        QueryIntent.COMPARISON,
        [
            _evidence(chunk_id="cp1", retrieval_query="agent cp1"),
            _evidence(chunk_id="cp2", retrieval_query="Agent CP2"),
        ],
        sub_queries=sub_queries,
    )

    assert result.accepted is True
    assert result.missing_targets == []
    assert len(result.evidence) == 2


def test_comparison_without_sub_queries_is_rejected() -> None:
    result = _evaluate(
        QueryIntent.COMPARISON,
        [_evidence()],
    )

    assert result.accepted is False
    assert result.reason == "comparison_sub_queries_missing"


@pytest.mark.parametrize(
    "intent",
    [
        QueryIntent.CASUAL_CHAT,
        QueryIntent.SYSTEM_HELP,
        QueryIntent.UNSUPPORTED,
    ],
)
def test_non_retrieval_intents_do_not_require_evidence(
    intent: QueryIntent,
) -> None:
    result = _evaluate(intent, [])

    assert result.accepted is True
    assert result.reason == "evidence_not_required"
    assert result.should_retry is False


def test_second_failed_attempt_does_not_retry_again() -> None:
    result = _evaluate(
        QueryIntent.KNOWLEDGE_QA,
        [],
        attempt=2,
    )

    assert result.accepted is False
    assert result.should_retry is False


@pytest.mark.parametrize("attempt", [0, 3])
def test_invalid_retrieval_attempt_is_rejected(attempt: int) -> None:
    plan = _plan(QueryIntent.KNOWLEDGE_QA)
    policy = IntentPolicyRouter().route(plan)

    with pytest.raises(ValueError, match="one or two"):
        EvidenceGate().evaluate(
            plan,
            policy,
            [],
            retrieval_attempt=attempt,
        )
