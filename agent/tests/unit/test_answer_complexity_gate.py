"""Direct tests for the gate that decides whether the completeness review runs.

Why this exists
---------------
``agent/answer/complexity.py`` is the single switch behind "should we spend an
LLM call on this answer". Its output feeds exactly two consumers:

1. ``AgentRunner._select_answer_llm`` (a no-op while ``ANSWER_FAST_MODEL`` is
   unset), and
2. ``AnswerCompletenessChecker.requires_llm_check`` -- the real one.

Measured behaviour on the evaluation set: the gate is right on 14 of 16 cases,
and its two misses are single-target-looking questions that in fact have large,
repairable coverage gaps. So its recall -- not just its happy path -- is load
bearing, and until this file it had **no test referencing it at all**.

These tests pin the four signals and all seven multi-aspect patterns, so any
change to the gate's thresholds is a deliberate, visible edit.
"""

import pytest

from agent.answer.complexity import answer_complexity_reasons, requires_complex_answer
from agent.schemas.query_plan import QueryIntent, QueryPlan

pytestmark = pytest.mark.no_storage


def _plan(
    query: str,
    *,
    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA,
    sub_queries: list[str] | None = None,
) -> QueryPlan:
    return QueryPlan(
        original_query=query,
        standalone_query=query,
        intent=intent,
        sub_queries=sub_queries or [],
    )


# --------------------------------------------------------------------------- #
# the four signals
# --------------------------------------------------------------------------- #
def test_single_target_question_is_not_complex() -> None:
    """The common case: a plain single-target lookup must stay on the cheap path.

    This is the shape of ``local_simple_query_plan_original_query``, a real case
    the gate correctly leaves alone.
    """
    plan = _plan("Which QueryPlan field stores the user's original question?")

    assert answer_complexity_reasons(plan) == []


def test_knowledge_qa_intent_alone_is_not_complex() -> None:
    assert answer_complexity_reasons(_plan("What is the ToolRegistry?", intent=QueryIntent.KNOWLEDGE_QA)) == []


@pytest.mark.parametrize("intent", [QueryIntent.COMPARISON, QueryIntent.SUMMARIZATION])
def test_comparison_and_summarization_intents_are_complex(intent: QueryIntent) -> None:
    assert f"intent:{intent.value}" in answer_complexity_reasons(_plan("Compare A with B", intent=intent))


def test_planned_sub_queries_are_complex() -> None:
    plan = _plan("Explain the flow", sub_queries=["first part", "second part"])

    assert answer_complexity_reasons(plan) == ["planned_sub_queries"]


def test_corrective_retrieval_is_complex() -> None:
    plan = _plan("What is the ToolRegistry?")

    assert answer_complexity_reasons(plan, retrieval_attempts=2) == ["corrective_retrieval"]


def test_a_single_retrieval_attempt_is_not_complex() -> None:
    assert answer_complexity_reasons(_plan("What is the ToolRegistry?"), retrieval_attempts=1) == []


# --------------------------------------------------------------------------- #
# the seven multi-aspect patterns
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("label", "query"),
    [
        ("from_to", "How does a request travel from entry to response?"),
        ("end_to_end", "Describe the end-to-end workflow of the pipeline."),
        ("how_and", "How do the Agent and the ToolExecutor interact?"),
        ("zh_from_to_steps", "请求从入口到最终响应需要哪些步骤？"),
        ("zh_complete_flow", "请说明完整的处理流程。"),
        ("zh_which_core_steps", "这个系统有哪些核心步骤？"),
        ("zh_how_and", "如何做重试并保证一致性？"),
    ],
)
def test_multi_aspect_patterns_fire(label: str, query: str) -> None:
    reasons = answer_complexity_reasons(_plan(query))

    assert "multi_aspect_scope" in reasons, f"{label} did not trigger"


# --------------------------------------------------------------------------- #
# composition
# --------------------------------------------------------------------------- #
def test_reasons_are_composed_in_stable_order_without_duplicates() -> None:
    plan = _plan(
        "How does the request travel from entry to response, and what happens then?",
        intent=QueryIntent.COMPARISON,
        sub_queries=["a", "b"],
    )

    assert answer_complexity_reasons(plan, retrieval_attempts=2) == [
        "intent:comparison",
        "planned_sub_queries",
        "corrective_retrieval",
        "multi_aspect_scope",
    ]


@pytest.mark.parametrize(
    ("plan", "attempts", "expected"),
    [
        (_plan("What is the ToolRegistry?"), 0, False),
        (_plan("What is the ToolRegistry?"), 2, True),
        (_plan("Explain the flow", sub_queries=["x", "y"]), 0, True),
    ],
)
def test_requires_complex_answer_is_the_boolean_of_reasons(
    plan: QueryPlan, attempts: int, expected: bool
) -> None:
    reasons = answer_complexity_reasons(plan, retrieval_attempts=attempts)

    assert requires_complex_answer(plan, retrieval_attempts=attempts) is bool(reasons)
    assert requires_complex_answer(plan, retrieval_attempts=attempts) is expected
