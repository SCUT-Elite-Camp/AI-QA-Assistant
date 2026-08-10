from unittest.mock import Mock

import pytest

from agent.query import (
    ClarificationDecision,
    IntentResult,
    QueryIntent,
    QueryEnrichment,
    QueryPreparationResult,
    QueryUnderstanding,
    RewriteResult,
    UnifiedQueryResult,
)


pytestmark = pytest.mark.no_storage


def _components(
    *,
    clarification: ClarificationDecision | None = None,
) -> tuple[Mock, Mock, Mock, Mock]:
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
    planner = Mock()
    planner.enrich.return_value = QueryEnrichment(
        sub_queries=["What is the leave policy for interns?"],
        filters={"doc_type": "policy"},
        reason="focused retrieval",
    )
    return classifier, clarifier, rewriter, planner


def test_analyze_combines_internal_results_into_query_plan() -> None:
    classifier, clarifier, rewriter, planner = _components()
    service = QueryUnderstanding(
        classifier, clarifier, rewriter, planner, cascaded_enabled=False
    )

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
    assert plan.sub_queries == ["What is the leave policy for interns?"]
    assert plan.filters == {"doc_type": "policy", "space_key": "HR"}
    planner.enrich.assert_called_once_with(
        "What is the leave policy for interns?",
        QueryIntent.KNOWLEDGE_QA,
    )


def test_clarification_stops_query_rewriting() -> None:
    classifier, clarifier, rewriter, planner = _components(
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
    service = QueryUnderstanding(
        classifier, clarifier, rewriter, planner, cascaded_enabled=False
    )

    plan = service.analyze("Compare them.", [])

    assert plan.needs_clarification is True
    assert plan.clarification_question == "Which two versions should be compared?"
    assert plan.standalone_query == "Compare them."
    rewriter.rewrite.assert_not_called()
    planner.enrich.assert_not_called()


def test_analyze_preserves_exact_original_query() -> None:
    classifier, clarifier, rewriter, planner = _components()
    rewriter.rewrite.return_value = RewriteResult(
        original_query="  What is RAG?  ",
        rewritten_query="What is RAG?",
        changed=False,
        reason="already standalone",
    )
    service = QueryUnderstanding(
        classifier, clarifier, rewriter, planner, cascaded_enabled=False
    )

    plan = service.analyze("  What is RAG?  ")

    assert plan.original_query == "  What is RAG?  "
    assert plan.standalone_query == "What is RAG?"


def test_analyze_does_not_mutate_history_or_filters() -> None:
    classifier, clarifier, rewriter, planner = _components()
    service = QueryUnderstanding(
        classifier, clarifier, rewriter, planner, cascaded_enabled=False
    )
    history = [{"role": "user", "content": "Previous question"}]
    filters = {"labels": ["cp2"]}

    plan = service.analyze("What about it?", history, filters=filters)
    plan.filters["labels"].append("changed")

    assert history == [{"role": "user", "content": "Previous question"}]
    assert filters == {"labels": ["cp2"]}


def test_unified_path_returns_query_plan_without_calling_legacy_components() -> None:
    classifier, clarifier, rewriter, planner = _components()
    unified = Mock()
    unified.analyze.return_value = UnifiedQueryResult(
        intent=QueryIntent.COMPARISON,
        confidence=0.97,
        standalone_query="Compare ToolExecutor and Evidence Gate.",
        sub_queries=["ToolExecutor responsibilities", "Evidence Gate responsibilities"],
    )
    service = QueryUnderstanding(
        classifier,
        clarifier,
        rewriter,
        planner,
        unified_analyzer=unified,
        unified_enabled=True,
        cascaded_enabled=False,
    )

    plan = service.analyze("Compare them.", [], filters={"space": "cp2"})

    assert plan.intent == QueryIntent.COMPARISON
    assert plan.intent_confidence == 0.97
    assert plan.filters == {"space": "cp2"}
    assert len(plan.sub_queries) == 2
    classifier.classify.assert_not_called()
    clarifier.evaluate.assert_not_called()
    rewriter.rewrite.assert_not_called()
    planner.enrich.assert_not_called()


def test_unified_failure_falls_back_to_legacy_pipeline() -> None:
    classifier, clarifier, rewriter, planner = _components()
    unified = Mock()
    unified.analyze.side_effect = ValueError("invalid response")
    service = QueryUnderstanding(
        classifier,
        clarifier,
        rewriter,
        planner,
        unified_analyzer=unified,
        unified_enabled=True,
        cascaded_enabled=False,
    )

    plan = service.analyze("What about interns?", [])

    assert plan.intent == QueryIntent.KNOWLEDGE_QA
    classifier.classify.assert_called_once()
    clarifier.evaluate.assert_called_once()
    rewriter.rewrite.assert_called_once()
    planner.enrich.assert_called_once()


def test_cascaded_path_uses_intent_gate_and_query_preparation() -> None:
    classifier, clarifier, rewriter, planner = _components()
    gate = Mock()
    gate.evaluate.return_value = ClarificationDecision(
        needs_clarification=False,
        reason="rule continue",
    )
    preparation = Mock()
    preparation.prepare.return_value = QueryPreparationResult(
        standalone_query="What is the leave policy for interns?",
        sub_queries=[],
        filters={"doc_type": "policy"},
    )
    service = QueryUnderstanding(
        classifier,
        clarifier,
        rewriter,
        planner,
        clarification_gate=gate,
        query_preparation=preparation,
        cascaded_enabled=True,
    )

    plan = service.analyze("What about interns?", [])

    assert plan.intent == QueryIntent.KNOWLEDGE_QA
    assert plan.standalone_query == "What is the leave policy for interns?"
    preparation.prepare.assert_called_once()
    rewriter.rewrite.assert_not_called()
    planner.enrich.assert_not_called()


def test_cascaded_non_retrieval_intent_skips_gate_and_preparation() -> None:
    classifier, clarifier, rewriter, planner = _components()
    classifier.classify.return_value = IntentResult(
        intent=QueryIntent.CASUAL_CHAT,
        confidence=0.99,
    )
    gate = Mock()
    preparation = Mock()
    service = QueryUnderstanding(
        classifier,
        clarifier,
        rewriter,
        planner,
        clarification_gate=gate,
        query_preparation=preparation,
        cascaded_enabled=True,
    )

    plan = service.analyze("Hello", [])

    assert plan.intent == QueryIntent.CASUAL_CHAT
    gate.evaluate.assert_not_called()
    preparation.prepare.assert_not_called()


def test_cascaded_preparation_failure_only_falls_back_rewrite_and_planner() -> None:
    classifier, clarifier, rewriter, planner = _components()
    gate = Mock()
    gate.evaluate.return_value = ClarificationDecision(
        needs_clarification=False,
        reason="rule continue",
    )
    preparation = Mock()
    preparation.prepare.side_effect = ValueError("invalid output")
    service = QueryUnderstanding(
        classifier,
        clarifier,
        rewriter,
        planner,
        clarification_gate=gate,
        query_preparation=preparation,
        cascaded_enabled=True,
    )

    plan = service.analyze("What about interns?", [])

    assert plan.standalone_query == "What is the leave policy for interns?"
    classifier.classify.assert_called_once()
    gate.evaluate.assert_called_once()
    rewriter.rewrite.assert_called_once()
    planner.enrich.assert_called_once()


def test_explicit_filters_override_semantic_filters() -> None:
    classifier, clarifier, rewriter, planner = _components()
    planner.enrich.return_value = QueryEnrichment(
        filters={"space": "model-space", "doc_type": "pdf"},
    )
    service = QueryUnderstanding(classifier, clarifier, rewriter, planner)

    plan = service.analyze(
        "What about interns?",
        filters={"space": "request-space"},
    )

    assert plan.filters == {"space": "request-space", "doc_type": "pdf"}


@pytest.mark.parametrize("query", ["", "   ", None])
def test_analyze_rejects_invalid_query(query: str | None) -> None:
    classifier, clarifier, rewriter, planner = _components()
    service = QueryUnderstanding(classifier, clarifier, rewriter, planner)

    with pytest.raises(ValueError, match="non-empty"):
        service.analyze(query)  # type: ignore[arg-type]

    classifier.classify.assert_not_called()
    clarifier.evaluate.assert_not_called()
    rewriter.rewrite.assert_not_called()
