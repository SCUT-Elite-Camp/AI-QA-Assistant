from unittest.mock import Mock

import pytest

from agent.query import (
    ClarificationDecision,
    IntentResult,
    QueryIntent,
    QueryUnderstanding,
    RewriteResult,
)


pytestmark = pytest.mark.no_storage


def _components(
    *,
    clarification: ClarificationDecision | None = None,
) -> tuple[Mock, Mock, Mock]:
    classifier = Mock()
    classifier.classify.return_value = IntentResult(
        intent=QueryIntent.KNOWLEDGE_QA,
        confidence=0.91,
        is_follow_up=True,
        is_clarification_reply=False,
        reason="follow-up",
    )
    clarifier = Mock()
    clarifier.evaluate.return_value = clarification or ClarificationDecision(
        needs_clarification=False,
        question="",
        reason="sufficient_context",
    )
    rewriter = Mock()
    rewriter.rewrite.return_value = RewriteResult(
        original_query="What about interns?",
        rewritten_query="What is the leave policy for interns?",
        changed=True,
        reason="resolved_reference",
    )
    return classifier, clarifier, rewriter


def test_analyze_combines_internal_results_into_query_plan() -> None:
    classifier, clarifier, rewriter = _components()
    service = QueryUnderstanding(classifier, clarifier, rewriter)

    plan = service.analyze(
        "What about interns?",
        [{"role": "user", "content": "Explain the leave policy."}],
        filters={"space_key": "HR"},
    )

    assert plan.original_query == "What about interns?"
    assert plan.standalone_query == "What is the leave policy for interns?"
    assert plan.intent == QueryIntent.KNOWLEDGE_QA
    assert plan.intent_confidence == 0.91
    assert plan.is_follow_up is True
    assert plan.needs_clarification is False
    assert plan.filters == {"space_key": "HR"}


def test_clarification_stops_query_rewriting() -> None:
    classifier, clarifier, rewriter = _components(
        clarification=ClarificationDecision(
            needs_clarification=True,
            question="Which two versions should be compared?",
            reason="comparison targets are missing",
        )
    )
    classifier.classify.return_value = IntentResult(
        intent=QueryIntent.COMPARISON,
        confidence=0.95,
        reason="comparison request",
    )
    service = QueryUnderstanding(classifier, clarifier, rewriter)

    plan = service.analyze("Compare them.", [])

    assert plan.needs_clarification is True
    assert plan.clarification_question == "Which two versions should be compared?"
    assert plan.standalone_query == "Compare them."
    rewriter.rewrite.assert_not_called()


def test_analyze_preserves_exact_original_query() -> None:
    classifier, clarifier, rewriter = _components()
    rewriter.rewrite.return_value = RewriteResult(
        original_query="  What is RAG?  ",
        rewritten_query="What is RAG?",
        changed=False,
        reason="already standalone",
    )
    service = QueryUnderstanding(classifier, clarifier, rewriter)

    plan = service.analyze("  What is RAG?  ")

    assert plan.original_query == "  What is RAG?  "
    assert plan.standalone_query == "What is RAG?"


def test_analyze_does_not_mutate_history_or_filters() -> None:
    classifier, clarifier, rewriter = _components()
    service = QueryUnderstanding(classifier, clarifier, rewriter)
    history = [{"role": "user", "content": "Previous question"}]
    filters = {"labels": ["cp2"]}

    plan = service.analyze("What about it?", history, filters=filters)
    plan.filters["labels"].append("changed")

    assert history == [{"role": "user", "content": "Previous question"}]
    assert filters == {"labels": ["cp2"]}


@pytest.mark.parametrize("query", ["", "   ", None])
def test_analyze_rejects_invalid_query(query: str | None) -> None:
    classifier, clarifier, rewriter = _components()
    service = QueryUnderstanding(classifier, clarifier, rewriter)

    with pytest.raises(ValueError, match="non-empty"):
        service.analyze(query)  # type: ignore[arg-type]

    classifier.classify.assert_not_called()
    clarifier.evaluate.assert_not_called()
    rewriter.rewrite.assert_not_called()
