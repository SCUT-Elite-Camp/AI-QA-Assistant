"""Regression tests for private/mixed scope coverage (not answer benchmarks)."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier
from types import SimpleNamespace

import pytest

from agent.agent import Agent
from agent.runtime import AgentRunner, StopReason
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan, SourceIntent, SourceKind
from agent.service.audit_service import AuditService
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool, ToolRegistry

pytestmark = pytest.mark.no_storage


class AnswerOnlyLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        assert tools is None
        self.calls += 1
        return {"role": "assistant", "content": "来源逐项回答 [1][2][3]"}


class SourceTool(BaseTool):
    def __init__(self, name, *, empty=False, unavailable=False):
        self.tool_name, self.empty, self.unavailable = name, empty, unavailable
        self.calls = []

    @property
    def name(self):
        return self.tool_name

    @property
    def description(self):
        return "controlled source transport"

    @property
    def parameters(self):
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [{"doc_id": "enterprise-one", "chunk_id": "enterprise-one::chunk_0", "chunk_index": 0,
            "chunk_text": "enterprise fact", "title": "enterprise", "score": 1.0}]

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.unavailable:
            return {"error": "service_unavailable", "items": []}
        if self.empty:
            return {"items": []}
        personal = self.name == "search_library"
        return {"items": [{"document_id": "personal-one", "attachment_id": "att_one",
            "evidence_id": "personal-block" if personal else "attached-block", "content": self.name,
            "filename": self.name, "score": 1.0, "version_id": "version-one", "knowledge_base_id": "kb-one"}]}


def run_mixed(*, empty=False, unavailable=False):
    tools = [SourceTool("search_documents"), SourceTool("search_library", empty=empty, unavailable=unavailable),
        SourceTool("search_attachments")]
    registry = ToolRegistryAdapter(ToolRegistry(tools=tools))
    llm = AnswerOnlyLLM()
    runner = AgentRunner(llm, registry, AuditService(), max_iterations=4)
    plan = QueryPlan(original_query="读取三个来源", standalone_query="读取三个来源",
        filters={"doc_ids": ["enterprise-one"]}, source_intent=SourceIntent(sources=list(SourceKind)))
    policy = IntentPolicy(candidate_tools=tuple(t.name for t in tools), max_tool_calls=4,
        max_retrieval_attempts=3, max_iterations=4, requires_citations=True)
    result = runner.run(plan, trace_id="multi-source-test", policy=policy, tool_executor=ToolExecutor(registry))
    return result, tools, llm


def test_mixed_reads_all_three_sources_before_clean_answer_optimization():
    result, tools, llm = run_mixed()
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert {item["source_type"] for item in result.evidence} == {"knowledge", "personal", "attachment"}
    assert [r.tool_name for r in result.tool_calls] == [t.name for t in tools]
    assert "doc_ids" not in tools[1].calls[0]
    assert llm.calls == 1


def test_missing_private_source_cannot_be_substituted_with_enterprise_hits():
    result, _, llm = run_mixed(empty=True)
    assert result.stop_reason == StopReason.NO_RELEVANT_CONTEXT
    assert result.error_code == "requested_source_evidence_missing"
    assert llm.calls == 0


def test_private_service_failure_is_not_a_successful_empty_retrieval():
    result, _, llm = run_mixed(unavailable=True)
    assert result.stop_reason == StopReason.TOOL_ERROR
    assert llm.calls == 0


def test_agent_memory_and_diagnostics_are_request_local():
    agent = Agent.__new__(Agent)
    agent._last_run_result = ContextVar("runs", default=None)
    agent._last_orchestration = ContextVar("orchestrations", default=None)
    agent._last_citation_check = ContextVar("citations", default=None)
    barrier = Barrier(2)

    def call(value):
        agent.last_run_result = agent.last_orchestration = agent.last_citation_check = value
        barrier.wait(timeout=5)
        return agent.last_run_result, agent.last_orchestration, agent.last_citation_check

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(call, "alice"), pool.submit(call, "bob")
        assert a.result() == ("alice",) * 3
        assert b.result() == ("bob",) * 3
    assert agent.last_orchestration is None


def test_enterprise_filters_are_not_personal_document_ids():
    plan = QueryPlan(original_query="my library", standalone_query="my library", filters={"doc_ids": ["confluence-id"]})
    result = AgentRunner._apply_execution_constraints(tool_name="search_library",
        arguments={"query": "untrusted", "doc_ids": ["other-owner"]}, query_plan=plan, mode="hybrid", top_k=5)
    assert result == {"query": "my library", "top_k": 5, "mode": "hybrid"}


def test_parallel_comparison_propagates_access_guard_before_tool_io():
    guard = object()
    calls = []

    class CheckedExecutor:
        registry = None

        def execute(self, **kwargs):
            assert CURRENT_ACCESS_GUARD.get() is guard
            calls.append(kwargs["arguments"]["query"])
            return SimpleNamespace(success=True, evidence=[])

    runner = AgentRunner(AnswerOnlyLLM(), ToolRegistryAdapter(ToolRegistry(tools=[])), AuditService())
    plan = QueryPlan(original_query="compare", standalone_query="compare", sub_queries=["W30", "W34"])
    token = CURRENT_ACCESS_GUARD.set(guard)
    try:
        runner._execute_parallel_comparison_retrieval(query_plan=plan, arguments={}, trace_id="guard-test",
            tool_call_id="comparison", tool_executor=CheckedExecutor(), retrieval_attempt=1)
    finally:
        CURRENT_ACCESS_GUARD.reset(token)
    assert sorted(calls) == ["W30", "W34"]
    assert CURRENT_ACCESS_GUARD.get() is None
