import pytest
from pydantic import ValidationError

from agent.schemas.query_plan import QueryIntent, QueryPlan


def test_query_plan_preserves_original_and_normalizes_runner_fields() -> None:
    plan = QueryPlan(
        original_query="  它的更新时间呢？ ",
        standalone_query="  AI-QA-Assistant 文档更新时间  ",
        intent=QueryIntent.DOCUMENT_SEARCH,
        sub_queries=["  子问题一 ", "", "   ", "子问题二"],
        filters={"space_key": "RAG"},
    )

    assert plan.original_query == "  它的更新时间呢？ "
    assert plan.standalone_query == "AI-QA-Assistant 文档更新时间"
    assert plan.sub_queries == ["子问题一", "子问题二"]
    assert plan.filters == {"space_key": "RAG"}


def test_clarification_question_is_required_only_for_clarification_plan() -> None:
    with pytest.raises(ValidationError, match="clarification_question"):
        QueryPlan(
            original_query="它怎么样？",
            standalone_query="它怎么样？",
            needs_clarification=True,
        )

    plan = QueryPlan(
        original_query="项目是什么？",
        standalone_query="项目是什么？",
        needs_clarification=False,
        clarification_question="不应保留",
    )
    assert plan.clarification_question == ""


def test_query_plan_rejects_unknown_fields_and_shared_mutable_defaults() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueryPlan(
            original_query="问题",
            standalone_query="问题",
            unknown_field=True,
        )

    first = QueryPlan(original_query="一", standalone_query="一")
    second = QueryPlan(original_query="二", standalone_query="二")
    first.filters["doc_id"] = "doc-1"
    first.sub_queries.append("子问题")

    assert second.filters == {}
    assert second.sub_queries == []
