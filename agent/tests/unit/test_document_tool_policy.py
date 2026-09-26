import pytest

from agent.policy import IntentPolicyRouter
from agent.runtime.runner import AgentRunner
from agent.schemas.query_plan import QueryIntent, QueryPlan


pytestmark = pytest.mark.no_storage


def _plan(intent=QueryIntent.SUMMARIZATION, filters=None):
    return QueryPlan(
        original_query="summarize policy",
        standalone_query="standalone policy query",
        intent=intent,
        filters=filters or {},
    )


def test_document_intents_expose_only_required_tools():
    router = IntentPolicyRouter()

    assert router.route(_plan(QueryIntent.DOCUMENT_SEARCH)).candidate_tools == (
        "find_documents",
    )
    assert router.route(_plan(QueryIntent.SUMMARIZATION)).candidate_tools == (
        "find_documents",
        "get_document",
        "search_documents",
    )


def test_find_documents_receives_validated_query_and_hard_filters():
    constrained = AgentRunner._apply_execution_constraints(
        tool_name="find_documents",
        arguments={"filters": {"space": "untrusted"}},
        query_plan=_plan(filters={"doc_ids": ["doc-1"], "space": "HR"}),
        mode="hybrid",
        top_k=7,
    )

    assert constrained == {
        "top_k": 7,
        "filters": {"doc_ids": ["doc-1"], "space": "HR"},
    }


def test_get_document_enforces_permission_allowlist():
    plan = _plan(filters={"doc_ids": ["doc-1"]})

    assert AgentRunner._apply_execution_constraints(
        tool_name="get_document",
        arguments={"doc_id": "doc-1", "offset": 0},
        query_plan=plan,
        mode="hybrid",
        top_k=5,
    )["doc_id"] == "doc-1"

    with pytest.raises(ValueError, match="document_not_allowed"):
        AgentRunner._apply_execution_constraints(
            tool_name="get_document",
            arguments={"doc_id": "doc-2"},
            query_plan=plan,
            mode="hybrid",
            top_k=5,
        )


def test_get_document_fails_closed_for_empty_allowlist():
    with pytest.raises(ValueError, match="document_not_allowed"):
        AgentRunner._apply_execution_constraints(
            tool_name="get_document",
            arguments={"doc_id": "doc-1"},
            query_plan=_plan(filters={"doc_ids": []}),
            mode="hybrid",
            top_k=5,
        )
