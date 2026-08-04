import pytest

from agent.evidence import EvidenceGateResult
from agent.policy import IntentPolicyRouter
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.schemas.query_plan import QueryIntent, QueryPlan


pytestmark = pytest.mark.no_storage


def _plan(
    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA,
    *,
    filters: dict | None = None,
    sub_queries: list[str] | None = None,
) -> QueryPlan:
    return QueryPlan(
        original_query="What about it?",
        standalone_query="What are the limitations of Agent CP2?",
        intent=intent,
        filters=filters or {},
        sub_queries=sub_queries or [],
    )


def _failed_gate(*, missing_targets: list[str] | None = None):
    return EvidenceGateResult(
        accepted=False,
        reason="insufficient",
        missing_targets=missing_targets or [],
        should_retry=True,
        retrieval_attempt=1,
    )


@pytest.mark.parametrize(
    ("previous_mode", "expected_mode"),
    [
        ("hybrid", "bm25"),
        ("bm25", "vector"),
        ("vector", "bm25"),
    ],
)
def test_corrective_retrieval_switches_mode_and_expands_top_k(
    previous_mode: str,
    expected_mode: str,
) -> None:
    plan = _plan()
    policy = IntentPolicyRouter().route(plan)

    requests = CorrectiveRetrievalPlanner().plan(
        plan,
        policy,
        _failed_gate(),
        previous_mode=previous_mode,
        previous_top_k=5,
    )

    assert len(requests) == 1
    assert requests[0].query == plan.standalone_query
    assert requests[0].mode == expected_mode
    assert requests[0].top_k == 10
    assert requests[0].retrieval_attempt == 2


def test_corrective_retrieval_preserves_hard_filters() -> None:
    filters = {"space": "CP2", "labels": ["agent"]}
    plan = _plan(filters=filters)
    policy = IntentPolicyRouter().route(plan)

    request = CorrectiveRetrievalPlanner().plan(
        plan,
        policy,
        _failed_gate(),
        previous_mode="hybrid",
        previous_top_k=5,
    )[0]
    request.filters["labels"].append("changed")

    assert plan.filters == {"space": "CP2", "labels": ["agent"]}
    assert filters == {"space": "CP2", "labels": ["agent"]}


def test_comparison_retries_only_missing_targets() -> None:
    plan = _plan(
        QueryIntent.COMPARISON,
        sub_queries=["Agent CP1", "Agent CP2"],
    )
    policy = IntentPolicyRouter().route(plan)

    requests = CorrectiveRetrievalPlanner().plan(
        plan,
        policy,
        _failed_gate(missing_targets=["Agent CP2"]),
        previous_mode="hybrid",
        previous_top_k=5,
    )

    assert [request.query for request in requests] == ["Agent CP2"]


def test_top_k_never_exceeds_contract_limit() -> None:
    plan = _plan()
    policy = IntentPolicyRouter().route(plan)

    request = CorrectiveRetrievalPlanner().plan(
        plan,
        policy,
        _failed_gate(),
        previous_mode="bm25",
        previous_top_k=20,
    )[0]

    assert request.top_k == 20


def test_no_retry_decision_returns_no_requests() -> None:
    plan = _plan()
    policy = IntentPolicyRouter().route(plan)
    gate = EvidenceGateResult(
        accepted=False,
        reason="second attempt failed",
        should_retry=False,
        retrieval_attempt=2,
    )

    assert CorrectiveRetrievalPlanner().plan(
        plan,
        policy,
        gate,
        previous_mode="hybrid",
        previous_top_k=5,
    ) == []


@pytest.mark.parametrize(
    ("mode", "top_k"),
    [("invalid", 5), ("hybrid", 0), ("hybrid", 21)],
)
def test_invalid_previous_retrieval_state_is_rejected(
    mode: str,
    top_k: int,
) -> None:
    plan = _plan()
    policy = IntentPolicyRouter().route(plan)

    with pytest.raises(ValueError):
        CorrectiveRetrievalPlanner().plan(
            plan,
            policy,
            _failed_gate(),
            previous_mode=mode,
            previous_top_k=top_k,
        )
