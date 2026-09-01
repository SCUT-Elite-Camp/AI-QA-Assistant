from unittest.mock import Mock

import pytest

from agent.policy import IntentPolicyRouter
from agent.query.schemas import IntentResult
from agent.query.subquery_router import SubQueryRouter
from agent.schemas.query_plan import QueryIntent, QueryPlan


pytestmark = pytest.mark.no_storage


def _plan(sub_queries: list[str]) -> QueryPlan:
    return QueryPlan(
        original_query="Summarize CP1 and compare it with CP2.",
        standalone_query="Summarize CP1 and compare it with CP2.",
        intent=QueryIntent.COMPARISON,
        sub_queries=sub_queries,
    )


def test_simple_plan_does_not_run_subquery_intent_routing() -> None:
    classifier = Mock()
    router = SubQueryRouter(classifier, IntentPolicyRouter())

    result = router.route(_plan([]))

    assert result.is_complex is False
    assert result.routes == ()
    classifier.classify.assert_not_called()


def test_each_complex_subquery_gets_its_own_intent_and_policy() -> None:
    classifier = Mock()
    classifier.classify.side_effect = [
        IntentResult(intent=QueryIntent.SUMMARIZATION, confidence=0.91),
        IntentResult(intent=QueryIntent.DOCUMENT_SEARCH, confidence=0.88),
    ]
    router = SubQueryRouter(classifier, IntentPolicyRouter())

    result = router.route(
        _plan(["Summarize the CP1 flow.", "Find the QueryPlan contract."])
    )

    assert result.is_complex is True
    assert [route.intent for route in result.routes] == [
        QueryIntent.SUMMARIZATION,
        QueryIntent.DOCUMENT_SEARCH,
    ]
    assert result.routes[0].policy.answer_style == "structured_summary"
    assert result.routes[1].policy.retrieval_strategy == "bm25"
    assert result.routes[1].policy.candidate_tools == ("search_documents",)
    assert classifier.classify.call_count == 2


def test_duplicate_subqueries_are_routed_once() -> None:
    classifier = Mock()
    classifier.classify.return_value = IntentResult(
        intent=QueryIntent.KNOWLEDGE_QA,
        confidence=0.9,
    )
    router = SubQueryRouter(classifier, IntentPolicyRouter())

    result = router.route(_plan(["Explain CP1.", "Explain CP1.", "Explain CP2."]))

    assert len(result.routes) == 2
    assert classifier.classify.call_count == 2


def test_explicit_subquery_actions_override_parent_intent() -> None:
    classifier = Mock()
    classifier.classify.side_effect = [
        IntentResult(intent=QueryIntent.COMPARISON, confidence=0.5),
        IntentResult(intent=QueryIntent.COMPARISON, confidence=0.5),
    ]
    router = SubQueryRouter(classifier, IntentPolicyRouter())

    result = router.route(
        _plan(["Summarize the CP1 flow.", "Compare CP1 and CP2."])
    )

    assert [route.intent for route in result.routes] == [
        QueryIntent.SUMMARIZATION,
        QueryIntent.COMPARISON,
    ]
