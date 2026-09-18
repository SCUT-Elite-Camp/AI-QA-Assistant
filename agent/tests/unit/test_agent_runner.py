import json
from typing import Any

import pytest

from agent.runtime import AgentRunner, StopReason
from agent.config.settings import settings
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.service.audit_service import AuditService
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool, ToolRegistry
from toolset.tool_layer.wiki_tool import (
    WikiReadPageTool, WikiReadSourcesTool, WikiSearchEvidenceTool, WikiSearchTool,
)


class ScriptedLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        self.calls.append({"messages": list(messages), "tools": tools})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RecordingTool(BaseTool):
    def __init__(self, name: str = "metadata_query") -> None:
        self._name = name
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A deterministic test tool."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        }

    def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return {"value": kwargs.get("value", "")}


class RecordingSearchTool(RecordingTool):
    def __init__(self) -> None:
        super().__init__(name="search_documents")

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return [
            {
                "doc_id": "doc-1",
                "chunk_id": "doc-1::chunk_0",
                "chunk_index": 0,
                "chunk_text": "检索证据",
                "title": "文档",
                "source_url": "https://example.com/doc-1",
                "score": 0.9,
            }
        ]


class WikiEvidenceTool(RecordingTool):
    def __init__(self) -> None:
        super().__init__(name="wiki_search_evidence")

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source_scope": {"type": "string"},
                "page_id": {"type": "string"},
                "top_k": {"type": "integer"},
                "mode": {"type": "string"},
            },
            "required": ["query", "page_id"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return {
            "citation_authority": True,
            "items": [
                {
                    "doc_id": "doc-1", "chunk_id": "doc-1::chunk_1",
                    "chunk_index": 1, "chunk_text": "planning evidence",
                    "title": "文档", "score": 0.9,
                    "document_id": "doc-1", "version_id": "ver-1",
                },
            ],
        }


def tool_call(
    name: str,
    arguments: dict[str, Any] | str,
    call_id: str = "call-1",
) -> dict[str, Any]:
    raw_arguments = (
        arguments if isinstance(arguments, str) else json.dumps(arguments)
    )
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": raw_arguments},
    }


def make_runner(llm: ScriptedLLM, tools: list[BaseTool], **kwargs) -> AgentRunner:
    return AgentRunner(
        llm=llm,
        registry=ToolRegistry(tools=tools),
        audit_service=AuditService(),
        **kwargs,
    )


def make_plan(**updates: Any) -> QueryPlan:
    values = {
        "original_query": "它讲了什么？",
        "standalone_query": "CP2 分工文档内容",
        "filters": {"space_key": "RAG"},
    }
    values.update(updates)
    return QueryPlan(**values)


def test_search_loop_uses_standalone_query_filters_and_trace_id() -> None:
    search = RecordingSearchTool()
    llm = ScriptedLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call("search_documents", {"query": "错误查询"})
                ],
            },
            {"role": "assistant", "content": "最终回答 [1]"},
        ]
    )
    runner = make_runner(llm, [search])

    result = runner.run(
        make_plan(),
        trace_id="trace-cp2",
        mode="bm25",
        top_k=3,
    )

    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.iterations == 2
    assert result.retrieval_attempts == 1
    assert len(result.evidence) == 1
    assert search.calls == [
        {
            "query": "CP2 分工文档内容",
            "top_k": 3,
            "mode": "bm25",
            "filters": {"space_key": "RAG"},
            "min_score": 0.0,
            "trace_id": "trace-cp2",
        }
    ]
    assert llm.calls[1]["messages"][-1]["role"] == "tool"


def test_direct_retrieval_constraints_use_only_traditional_search_contract() -> None:
    constrained = AgentRunner._apply_execution_constraints(
        tool_name="search_documents",
        arguments={"query": "draft"},
        query_plan=make_plan(),
        mode="hybrid",
        top_k=5,
    )

    assert constrained["query"] == "CP2 分工文档内容"
    assert set(constrained) == {"query", "top_k", "mode", "filters"}


def test_wiki_scope_is_forced_to_server_authorized_source() -> None:
    constrained = AgentRunner._apply_execution_constraints(
        tool_name="wiki_search",
        arguments={"query": "draft", "source_scope": "enterprise"},
        query_plan=make_plan(),
        mode="hybrid",
        top_k=5,
        navigation_scopes=("personal",),
    )

    assert constrained["source_scope"] == "personal"


def test_navigation_without_authorized_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="not authorized"):
        AgentRunner._apply_execution_constraints(
            tool_name="wiki_search",
            arguments={"query": "draft"},
            query_plan=make_plan(),
            mode="hybrid",
            top_k=5,
        )


def test_complex_auto_mode_prefetches_direct_before_first_llm_turn(monkeypatch) -> None:
    search = RecordingSearchTool()
    wiki_evidence = WikiEvidenceTool()
    registry = ToolRegistry(tools=[search])
    registry.register_tool(wiki_evidence)
    runner = AgentRunner(
        llm=ScriptedLLM([
            {
                "role": "assistant", "content": None,
                "tool_calls": [tool_call(
                    "wiki_search_evidence",
                    {
                        "query": "draft", "source_scope": "enterprise",
                        "page_id": "wiki-page-1",
                    },
                    "call-wiki-evidence",
                )],
            },
            {"role": "assistant", "content": "完整回答 [1]"},
        ]),
        registry=registry,
        audit_service=AuditService(),
    )
    monkeypatch.setattr(settings, "AGENTIC_EXPLORATION_ENABLED", True)

    result = runner.run(
        make_plan(),
        policy=IntentPolicy(
            candidate_tools=("search_documents", "wiki_search_evidence"),
            max_iterations=5,
            max_tool_calls=6,
            max_retrieval_attempts=5,
        ),
        tool_executor=ToolExecutor(ToolRegistryAdapter(registry)),
        trace_id="trace-prefetch",
        exploration_mode="force",
        navigation_scopes=("enterprise",),
    )

    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.tool_calls[0].tool_call_id == "initial-direct-1"
    assert result.evidence[0]["chunk_id"] == "doc-1::chunk_0"
    assert result.exploration_rounds == 1
    assert len(result.evidence) == 2
    assert any(
        "mandatory initial Direct retrieval" in message.get("content", "")
        for message in runner.llm.calls[0]["messages"]
    )


def test_simple_query_with_wiki_available_still_searches_direct_first(monkeypatch) -> None:
    search = RecordingSearchTool()
    wiki = RecordingTool("wiki_search")
    runner = make_runner(ScriptedLLM([{"role": "assistant", "content": "根据原文回答 [1]"}]),
                         [search, wiki])
    monkeypatch.setattr(settings, "AGENTIC_EXPLORATION_ENABLED", True)
    result = runner.run(
        make_plan(original_query="CP2 是什么？", standalone_query="CP2"),
        policy=IntentPolicy(candidate_tools=("search_documents", "wiki_search"),
                            max_iterations=4, max_tool_calls=5, max_retrieval_attempts=3),
        tool_executor=ToolExecutor(ToolRegistryAdapter(runner.registry)),
        trace_id="trace-simple-direct", exploration_mode="auto",
        navigation_scopes=("enterprise",),
    )
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.tool_calls[0].tool_name == "search_documents"
    assert search.calls and not wiki.calls


def test_explicit_wiki_exploration_returns_to_versioned_evidence(monkeypatch) -> None:
    class ScopedSearch(RecordingSearchTool):
        def search(self, **kwargs):
            self.calls.append(kwargs)
            document_id = (kwargs.get("filters") or {}).get("doc_ids", ["doc-1"])[0]
            return [{
                "doc_id": document_id, "document_id": document_id,
                "version_id": "ver-2" if document_id == "doc-2" else "ver-1",
                "chunk_id": f"{document_id}::evidence", "chunk_index": 0,
                "chunk_text": "Original Evidence", "title": "Source",
                "score": 0.9,
            }]

    class ScopedWiki:
        def search_pages(self, query, **kwargs):
            return [{"page_id": "page-2", "title": "Related concept"}]

        def read_page(self, page_ref, **kwargs):
            return {"id": page_ref, "title": "Related concept"}

        def read_sources(self, page_id, **kwargs):
            return [{"document_id": "doc-2", "document_version_id": "ver-2",
                     "evidence_id": "doc-2::evidence", "section_id": "sec-2"}]

    search = ScopedSearch()
    store = ScopedWiki()
    tools = [
        search,
        WikiSearchTool(store, enterprise_knowledge_base_id="kb"),
        WikiReadPageTool(store, enterprise_knowledge_base_id="kb"),
        WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb"),
        WikiSearchEvidenceTool(store, search, enterprise_knowledge_base_id="kb"),
    ]
    registry = ToolRegistry(tools=tools)
    llm = ScriptedLLM([
        {"tool_calls": [tool_call("wiki_search", {"query": "related"}, "wiki-1")]},
        {"tool_calls": [tool_call("wiki_read_page", {"page_ref": "page-2"}, "wiki-2")]},
        {"tool_calls": [tool_call("wiki_read_sources", {"page_id": "page-2"}, "wiki-3")]},
        {"tool_calls": [tool_call("wiki_search_evidence", {
            "query": "related", "page_id": "page-2",
        }, "wiki-4")]},
        {"role": "assistant", "content": "根据两份原始证据回答 [1][2]"},
    ])
    runner = AgentRunner(llm=llm, registry=registry, audit_service=AuditService())
    monkeypatch.setattr(settings, "AGENTIC_EXPLORATION_ENABLED", True)
    result = runner.run(
        make_plan(original_query="跨文档对比两个主题", standalone_query="跨文档主题比较"),
        policy=IntentPolicy(
            candidate_tools=tuple(tool.name for tool in tools),
            max_iterations=7, max_tool_calls=8, max_retrieval_attempts=5,
        ),
        tool_executor=ToolExecutor(ToolRegistryAdapter(registry)),
        trace_id="trace-wiki-chain", exploration_mode="auto",
        navigation_scopes=("enterprise",),
    )
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert [call.tool_name for call in result.tool_calls] == [
        "search_documents", "wiki_search", "wiki_read_page",
        "wiki_read_sources", "wiki_search_evidence",
    ]
    assert result.exploration_rounds == 4
    assert {item["document_id"] for item in result.evidence} == {"doc-1", "doc-2"}
    assert search.calls[-1]["filters"] == {"doc_ids": ["doc-2"]}


def test_runner_supports_multiple_different_tool_iterations() -> None:
    first = RecordingTool("first_tool")
    second = RecordingTool("second_tool")
    llm = ScriptedLLM(
        [
            {"tool_calls": [tool_call("first_tool", {"value": "A"}, "call-a")]},
            {"tool_calls": [tool_call("second_tool", {"value": "B"}, "call-b")]},
            {"content": "组合后的最终回答"},
        ]
    )
    runner = make_runner(llm, [first, second])

    result = runner.run(make_plan(), trace_id="trace-multi")

    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.iterations == 3
    assert [record.tool_name for record in result.tool_calls] == [
        "first_tool",
        "second_tool",
    ]
    assert first.calls == [{"value": "A"}]
    assert second.calls == [{"value": "B"}]


def test_runner_stops_immediately_on_final_answer_without_tool_call() -> None:
    llm = ScriptedLLM([{"role": "assistant", "content": "直接回答"}])
    runner = make_runner(llm, [])

    result = runner.run(make_plan(), trace_id="trace-final")

    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.iterations == 1
    assert result.tool_calls == []


def test_clarification_plan_skips_llm_and_tools() -> None:
    tool = RecordingTool()
    llm = ScriptedLLM([])
    runner = make_runner(llm, [tool])

    result = runner.run(
        make_plan(
            needs_clarification=True,
            clarification_question="你指的是哪个文档？",
        ),
        trace_id="trace-clarify",
    )

    assert result.stop_reason == StopReason.CLARIFICATION_REQUIRED
    assert result.iterations == 0
    assert result.message == "你指的是哪个文档？"
    assert llm.calls == []
    assert tool.calls == []


def test_repeated_identical_tool_call_is_stopped_before_second_execution() -> None:
    tool = RecordingTool()
    repeated = {"tool_calls": [tool_call("metadata_query", {"value": "same"})]}
    llm = ScriptedLLM([repeated, repeated])
    runner = make_runner(llm, [tool], max_repeated_tool_calls=2)

    result = runner.run(make_plan(), trace_id="trace-repeat")

    assert result.stop_reason == StopReason.REPEATED_TOOL_CALL
    assert result.iterations == 2
    assert tool.calls == [{"value": "same"}]
    assert result.tool_calls[-1].error_code == "repeated_tool_call"


def test_repeated_wiki_search_gets_one_bounded_read_page_correction() -> None:
    wiki_search = RecordingTool("wiki_search")
    wiki_page = RecordingTool("wiki_read_page")
    llm = ScriptedLLM([
        {"tool_calls": [tool_call("wiki_search", {"query": "topic"}, "wiki-first")]},
        {"tool_calls": [tool_call("wiki_search", {"query": "topic"}, "wiki-repeat")]},
        {"tool_calls": [tool_call("wiki_read_page", {"page_ref": "page-1"}, "wiki-page")]},
        {"role": "assistant", "content": "导航完成"},
    ])
    runner = make_runner(llm, [wiki_search, wiki_page], max_repeated_tool_calls=2)
    result = runner.run(
        make_plan(), trace_id="trace-wiki-repeat", exploration_mode="force",
        navigation_scopes=("enterprise",),
        policy=IntentPolicy(
            candidate_tools=("wiki_search", "wiki_read_page"),
            max_iterations=4, max_tool_calls=4, requires_citations=False,
        ),
    )

    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert len(wiki_search.calls) == 1
    assert len(wiki_page.calls) == 1
    assert result.tool_calls[1].error_code == "repeated_tool_call"
    assert any(
        message.get("tool_call_id") == "wiki-repeat"
        and "wiki_read_page" in message.get("content", "")
        for message in llm.calls[2]["messages"]
    )


def test_wiki_source_steps_restrict_next_tool_and_reject_skips() -> None:
    class PageSearch(RecordingTool):
        def execute(self, **kwargs):
            self.calls.append(kwargs)
            return {"pages": [{"page_id": "page-1"}], "citation_authority": False}

    search = PageSearch("wiki_search")
    evidence = RecordingTool("wiki_search_evidence")
    registry = ToolRegistry(tools=[search, evidence, RecordingTool("wiki_read_page")])
    llm = ScriptedLLM([
        {"tool_calls": [tool_call("wiki_search", {"query": "topic"}, "search")]},
        {"tool_calls": [tool_call("wiki_search_evidence", {
            "query": "topic", "page_id": "page-1",
        }, "skip-sources")]},
    ])
    runner = AgentRunner(llm=llm, registry=registry, audit_service=AuditService())
    result = runner.run(
        make_plan(), trace_id="trace-wiki-order", exploration_mode="force",
        navigation_scopes=("enterprise",),
        policy=IntentPolicy(
            candidate_tools=("wiki_search", "wiki_read_page", "wiki_search_evidence"),
            max_iterations=2, max_tool_calls=4, requires_citations=False,
        ),
    )

    assert result.stop_reason == StopReason.MAX_ITERATIONS
    assert result.tool_calls[-1].error_code == "navigation_step_out_of_order"
    assert not evidence.calls
    assert [schema["function"]["name"] for schema in llm.calls[1]["tools"]] == ["wiki_read_page"]


def test_max_iterations_stops_changing_tool_calls() -> None:
    tool = RecordingTool()
    llm = ScriptedLLM(
        [
            {"tool_calls": [tool_call("metadata_query", {"value": "one"}, "one")]},
            {"tool_calls": [tool_call("metadata_query", {"value": "two"}, "two")]},
        ]
    )
    runner = make_runner(llm, [tool], max_iterations=2)

    result = runner.run(make_plan(), trace_id="trace-max")

    assert result.stop_reason == StopReason.MAX_ITERATIONS
    assert result.iterations == 2
    assert len(tool.calls) == 2


def test_low_score_search_result_stops_before_second_llm_call(
    monkeypatch,
) -> None:
    monkeypatch.setattr("agent.runtime.runner.settings.MIN_RETRIEVAL_SCORE", 0.95)
    search = RecordingSearchTool()
    llm = ScriptedLLM(
        [{"tool_calls": [tool_call("search_documents", {"query": "ignored"})]}]
    )
    runner = make_runner(llm, [search])

    result = runner.run(make_plan(), trace_id="trace-low-score")

    assert result.stop_reason == StopReason.NO_RELEVANT_CONTEXT
    assert len(llm.calls) == 1
    assert result.evidence == []


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (["not", "an", "object"], "invalid_llm_response"),
        ({"tool_calls": {"not": "a list"}}, "invalid_tool_calls"),
    ],
)
def test_malformed_llm_response_is_a_controlled_error(
    response: Any,
    error_code: str,
) -> None:
    runner = make_runner(ScriptedLLM([response]), [])

    result = runner.run(make_plan(), trace_id="trace-malformed")

    assert result.stop_reason == StopReason.LLM_ERROR
    assert result.error_code == error_code


@pytest.mark.parametrize(
    ("call", "expected_error"),
    [
        (tool_call("missing_tool", {}), "tool_not_found"),
        (tool_call("metadata_query", "{not-json"), "tool arguments are not valid JSON"),
    ],
)
def test_unknown_tool_and_invalid_json_are_controlled_errors(
    call: dict[str, Any],
    expected_error: str,
) -> None:
    llm = ScriptedLLM([{"tool_calls": [call]}])
    runner = make_runner(llm, [RecordingTool()])

    result = runner.run(make_plan(), trace_id="trace-tool-error")

    assert result.stop_reason == StopReason.TOOL_ERROR
    assert expected_error in result.error_code
