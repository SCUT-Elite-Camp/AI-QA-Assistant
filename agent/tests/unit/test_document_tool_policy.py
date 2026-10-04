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


def test_find_documents_is_intermediate_in_summarization():
    class FakeDocTool:
        name = "find_documents"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return {"documents": [{"doc_id": "doc-1", "title": "Doc 1"}], "result_count": 1}

    class FakeRegistry:
        def get(self, name):
            return FakeDocTool()

    from agent.service.audit_service import AuditService
    from agent.tools.executor import ToolExecutor
    from agent.tools.registry import ToolRegistryAdapter

    runner = AgentRunner(llm=None, audit_service=AuditService(), registry=FakeRegistry())
    executor = ToolExecutor(FakeRegistry())
    plan = _plan(intent=QueryIntent.SUMMARIZATION)

    observation, evidence, is_retrieval = runner._execute_tool(
        tool=FakeDocTool(),
        tool_name="find_documents",
        arguments={"query": "test"},
        query_plan=plan,
        trace_id="test-trace",
        tool_call_id="call-1",
        tool_executor=executor,
    )

    assert is_retrieval is False
    assert evidence == []
    assert "doc-1" in observation


def test_find_documents_is_retrieval_in_document_search():
    class FakeDocTool:
        name = "find_documents"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return {"documents": [{"doc_id": "doc-1", "title": "Doc 1"}], "result_count": 1}

    class FakeRegistry:
        def get(self, name):
            return FakeDocTool()

    from agent.service.audit_service import AuditService
    from agent.tools.executor import ToolExecutor

    runner = AgentRunner(llm=None, audit_service=AuditService(), registry=FakeRegistry())
    executor = ToolExecutor(FakeRegistry())
    plan = _plan(intent=QueryIntent.DOCUMENT_SEARCH)

    observation, evidence, is_retrieval = runner._execute_tool(
        tool=FakeDocTool(),
        tool_name="find_documents",
        arguments={"query": "test"},
        query_plan=plan,
        trace_id="test-trace",
        tool_call_id="call-1",
        tool_executor=executor,
    )

    assert is_retrieval is True
    assert len(evidence) == 1
    assert evidence[0]["doc_id"] == "doc-1"
