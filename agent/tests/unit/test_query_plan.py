import pytest
from pydantic import ValidationError

from agent.query import QueryIntent as QueryIntentFromQuery
from agent.query import QueryPlan as QueryPlanFromQuery
from agent.schemas.query_plan import QueryIntent, QueryPlan


pytestmark = pytest.mark.no_storage


def test_query_package_reexports_the_canonical_contract() -> None:
    assert QueryIntentFromQuery is QueryIntent
    assert QueryPlanFromQuery is QueryPlan


def test_query_intent_contains_cp2_supported_values() -> None:
    assert {intent.value for intent in QueryIntent} == {
        "knowledge_qa",
        "document_search",
        "summarization",
        "comparison",
        "casual_chat",
        "system_help",
        "unsupported",
    }


def test_query_plan_uses_safe_cp2_defaults() -> None:
    plan = QueryPlan(
        original_query="CP2 的目标是什么？",
        standalone_query="CP2 的目标是什么？",
    )

    assert plan.intent == QueryIntent.KNOWLEDGE_QA
    assert plan.intent_confidence == 1.0
    assert plan.is_follow_up is False
    assert plan.is_clarification_reply is False
    assert plan.needs_clarification is False
    assert plan.clarification_question == ""
    assert plan.ambiguity_reason == ""
    assert plan.sub_queries == []
    assert plan.filters == {}


def test_query_plan_preserves_original_and_normalizes_standalone_query() -> None:
    plan = QueryPlan(
        original_query="  它有哪些不足？  ",
        standalone_query="  Agent 层 Q1 当前实现有哪些不足？  ",
        is_follow_up=True,
    )

    assert plan.original_query == "  它有哪些不足？  "
    assert plan.standalone_query == "Agent 层 Q1 当前实现有哪些不足？"
    assert plan.is_follow_up is True


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_intent_confidence_must_be_between_zero_and_one(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        QueryPlan(
            original_query="问题",
            standalone_query="问题",
            intent_confidence=confidence,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_query", ""),
        ("original_query", "   "),
        ("standalone_query", ""),
        ("standalone_query", "   "),
    ],
)
def test_query_fields_must_not_be_empty(field: str, value: str) -> None:
    data = {
        "original_query": "原始问题",
        "standalone_query": "独立问题",
        field: value,
    }

    with pytest.raises(ValidationError):
        QueryPlan(**data)


def test_clarification_requires_a_specific_question() -> None:
    with pytest.raises(ValidationError, match="clarification_question"):
        QueryPlan(
            original_query="帮我比较一下",
            standalone_query="帮我比较一下",
            intent=QueryIntent.COMPARISON,
            needs_clarification=True,
        )


def test_clarification_plan_keeps_question_and_reason() -> None:
    plan = QueryPlan(
        original_query="帮我比较一下",
        standalone_query="帮我比较一下",
        intent=QueryIntent.COMPARISON,
        needs_clarification=True,
        clarification_question="  请问需要比较哪些对象？  ",
        ambiguity_reason="  缺少比较对象  ",
    )

    assert plan.clarification_question == "请问需要比较哪些对象？"
    assert plan.ambiguity_reason == "缺少比较对象"


def test_non_clarification_plan_discards_unused_question() -> None:
    plan = QueryPlan(
        original_query="什么是 RAG？",
        standalone_query="什么是 RAG？",
        needs_clarification=False,
        clarification_question="不应保留",
    )

    assert plan.clarification_question == ""


def test_sub_queries_are_normalized() -> None:
    plan = QueryPlan(
        original_query="比较 CP1 和 CP2",
        standalone_query="比较 CP1 和 CP2",
        intent=QueryIntent.COMPARISON,
        sub_queries=["  CP1 的目标  ", "", "  ", "CP2 的目标"],
    )

    assert plan.sub_queries == ["CP1 的目标", "CP2 的目标"]


def test_mutable_defaults_are_isolated_between_plans() -> None:
    first = QueryPlan(original_query="问题一", standalone_query="问题一")
    second = QueryPlan(original_query="问题二", standalone_query="问题二")

    first.sub_queries.append("子问题")
    first.filters["doc_type"] = "md"

    assert second.sub_queries == []
    assert second.filters == {}


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueryPlan(
            original_query="问题",
            standalone_query="问题",
            unknown_policy="not allowed",
        )


def test_query_plan_serializes_intent_as_string() -> None:
    plan = QueryPlan(
        original_query="比较 CP1 和 CP2",
        standalone_query="比较 CP1 和 CP2",
        intent=QueryIntent.COMPARISON,
    )

    assert plan.model_dump(mode="json")["intent"] == "comparison"
