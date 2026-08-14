import json

import pytest

from agent.llm.base import BaseLLM
from agent.query import QueryIntent, QueryPlanner


pytestmark = pytest.mark.no_storage


class FakeLLM(BaseLLM):
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {}
        self.error = error
        self.messages: list[dict] | None = None

    def generate(self, prompt: str) -> str:
        return ""

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        self.messages = messages
        if self.error:
            raise self.error
        return self.response


def _response(payload: dict) -> dict:
    return {"content": json.dumps(payload, ensure_ascii=False)}


def test_comparison_generates_normalized_unique_sub_queries() -> None:
    planner = QueryPlanner(
        llm=FakeLLM(
            _response(
                {
                    "sub_queries": [
                        "  HSBC 2024 profit ",
                        "Barclays 2024 profit",
                        "HSBC 2024 profit",
                    ],
                    "filters": {},
                    "reason": "one query per target",
                }
            )
        )
    )

    result = planner.enrich(
        "Compare HSBC and Barclays 2024 profit",
        QueryIntent.COMPARISON,
    )

    assert result.sub_queries == [
        "HSBC 2024 profit",
        "Barclays 2024 profit",
    ]


def test_only_toolset_supported_filters_are_kept() -> None:
    planner = QueryPlanner(
        llm=FakeLLM(
            _response(
                {
                    "sub_queries": [],
                    "filters": {
                        "space": "CP2",
                        "doc_type": "md",
                        "year": 2024,
                        "unknown": "discard",
                    },
                    "reason": "explicit filters",
                }
            )
        )
    )

    result = planner.enrich("Find CP2 markdown documents", QueryIntent.DOCUMENT_SEARCH)

    assert result.filters == {"space": "CP2", "doc_type": "md"}


@pytest.mark.parametrize(
    "intent",
    [QueryIntent.CASUAL_CHAT, QueryIntent.SYSTEM_HELP, QueryIntent.UNSUPPORTED],
)
def test_non_retrieval_intents_skip_llm(intent: QueryIntent) -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    planner = QueryPlanner(llm=llm)

    result = planner.enrich("Hello", intent)

    assert result.sub_queries == []
    assert result.filters == {}
    assert result.reason == "query_planning_skipped"
    assert llm.messages is None


def test_simple_knowledge_qa_skips_planner_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    planner = QueryPlanner(llm=llm)

    result = planner.enrich("CitationChecker 检查什么？", QueryIntent.KNOWLEDGE_QA)

    assert result.sub_queries == []
    assert result.filters == {}
    assert result.reason == "simple_knowledge_qa_fast_path"
    assert llm.messages is None


def test_multi_aspect_knowledge_qa_keeps_planner_llm() -> None:
    llm = FakeLLM(
        _response(
            {
                "sub_queries": ["ToolRegistry ownership", "Agent tool schema discovery"],
                "filters": {},
                "reason": "two requested aspects",
            }
        )
    )
    planner = QueryPlanner(llm=llm)

    result = planner.enrich(
        "ToolRegistry 由哪一层拥有，Agent 如何通过它发现工具？",
        QueryIntent.KNOWLEDGE_QA,
    )

    assert len(result.sub_queries) == 2
    assert llm.messages is not None


@pytest.mark.parametrize(
    "response",
    [
        {"content": "not-json"},
        {"content": "[]"},
        {"content": '{"sub_queries":"wrong","filters":{},"reason":""}'},
        {"content": '{"sub_queries":[],"filters":{},"extra":true}'},
        {"content": None},
    ],
)
def test_invalid_response_uses_empty_fallback(response: dict) -> None:
    planner = QueryPlanner(llm=FakeLLM(response))

    result = planner.enrich(
        "What is CP2 and how does it differ from CP1?",
        QueryIntent.KNOWLEDGE_QA,
    )

    assert result.sub_queries == []
    assert result.filters == {}
    assert result.reason == "query_planning_failed"


def test_llm_error_uses_empty_fallback() -> None:
    planner = QueryPlanner(llm=FakeLLM(error=RuntimeError("unavailable")))

    result = planner.enrich(
        "What is CP2 and how does it differ from CP1?",
        QueryIntent.KNOWLEDGE_QA,
    )

    assert result.sub_queries == []
    assert result.filters == {}


def test_at_most_four_sub_queries_are_returned() -> None:
    planner = QueryPlanner(
        llm=FakeLLM(
            _response(
                {
                    "sub_queries": ["q1", "q2", "q3", "q4", "q5"],
                    "filters": {},
                    "reason": "decomposed",
                }
            )
        )
    )

    result = planner.enrich("Complex request", QueryIntent.SUMMARIZATION)

    assert result.sub_queries == ["q1", "q2", "q3", "q4"]
