import json
from typing import Any

from agent.agent import Agent
from agent.config.settings import settings
from agent.schemas.chat import ChatRequest
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent, SourceKind
from agent.streaming.sse import chat_response_events
from toolset.tool_layer import BaseTool


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


class ExplorationLLM:
    def __init__(self) -> None:
        self.responses = [
            {"tool_calls": [tool_call("search_documents", {"query": "ignored"}, "direct")]},
            {"tool_calls": [tool_call("wiki_read_page", {"page_ref": "page-1"}, "page")]},
            {"tool_calls": [tool_call("wiki_read_sources", {"page_id": "page-1"}, "sources")]},
            {"tool_calls": [tool_call(
                "wiki_search_evidence", {"query": "ignored", "page_id": "page-1"}, "evidence",
            )]},
            {"role": "assistant", "content": "A [1] and B [2] are covered."},
        ]

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        return self.responses.pop(0)


class DirectSearch(BaseTool):
    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Search deterministic integration evidence."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    def execute(self, **kwargs: Any) -> Any:
        return self.search(**kwargs)

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        query = kwargs["query"]
        return [{
            "doc_id": f"direct-{query}",
            "chunk_id": f"direct-{query}::chunk-0",
            "chunk_text": f"Authoritative evidence for {query}.",
            "title": f"Direct {query}",
            "source_url": f"https://example.test/{query}",
            "score": 0.95,
            "locator": {"section_id": f"section-{query}"},
        }]


class WikiTool(BaseTool):
    _payloads = {
        "wiki_search": {"pages": [{"page_id": "page-1", "title": "Related"}]},
        "wiki_read_page": {"page": {"id": "page-1", "title": "Related"}},
        "wiki_read_sources": {
            "sources": [{"document_id": "wiki-doc", "document_version_id": "v1"}],
        },
        "wiki_search_evidence": {
            "citation_authority": True,
            "items": [{
                "doc_id": "wiki-doc",
                "document_id": "wiki-doc",
                "version_id": "v1",
                "chunk_id": "wiki-doc::chunk-0",
                "chunk_text": "Additional original evidence.",
                "title": "Wiki source document",
                "source_url": "https://example.test/wiki-doc",
                "score": 0.95,
            }],
        },
    }

    def __init__(self, tool_name: str) -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Bounded deterministic Wiki navigation stub."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    def execute(self, **kwargs: Any) -> Any:
        return self._payloads[self._name]


class FixedComparisonPlan:
    def analyze(self, query: str, history=None, *, filters=None) -> QueryPlan:
        return QueryPlan(
            original_query=query,
            standalone_query="compare A and B",
            intent=QueryIntent.COMPARISON,
            sub_queries=["A", "B"],
            source_intent=SourceIntent(sources=[SourceKind.ENTERPRISE_KB]),
        )


class ExplorationPolicyRouter:
    def route(self, query_plan: QueryPlan) -> IntentPolicy:
        return IntentPolicy(
            candidate_tools=("search_documents",),
            evidence_policy="bilateral_coverage",
            answer_style="comparison_table",
            max_iterations=6,
            max_tool_calls=8,
            max_retrieval_attempts=5,
        )


def test_agent_chat_and_sse_keep_public_contract_during_exploration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AGENTIC_EXPLORATION_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(settings, "ANSWER_TARGET_EXTRACT_LLM", False)
    llm = ExplorationLLM()
    agent = Agent(
        llm=llm,
        tools=[
            DirectSearch(),
            *(WikiTool(name) for name in (
                "wiki_search", "wiki_read_page", "wiki_read_sources",
                "wiki_search_evidence",
            )),
        ],
        query_understanding=FixedComparisonPlan(),  # type: ignore[arg-type]
        policy_router=ExplorationPolicyRouter(),  # type: ignore[arg-type]
    )

    response = agent.chat(ChatRequest(
        query="compare A and B",
        weight_mode="thinking",
        exploration_mode="auto",
        is_first_message=False,
    ))

    assert response.status == "success"
    assert set(response.model_dump()) == {
        "trace_id", "status", "answer", "message", "citations", "chat_title",
    }
    assert agent.last_run_result is not None
    assert agent.last_run_result.coverage_assessments[0]["should_explore"] is True
    assert [call.tool_name for call in agent.last_run_result.tool_calls] == [
        "search_documents", "wiki_search", "wiki_read_page",
        "wiki_read_sources", "wiki_search_evidence",
    ]

    events = list(chat_response_events(response))
    assert [name for name, _ in events] == ["citations", "token", "done"]
    assert events[0][1] == [citation.model_dump() for citation in response.citations]
    assert set(events[-1][1]) == {
        "trace_id", "status", "citations_count", "chat_title",
    }
