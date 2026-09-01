import json

import pytest

from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query import QueryIntent, QueryPreparationAnalyzer


pytestmark = pytest.mark.no_storage


class FakeLLM(BaseLLM):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls += 1
        return {"content": json.dumps(self.payload)}


class InvalidLLM(FakeLLM):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls += 1
        return {"content": "not valid JSON"}


def test_prepare_combines_rewrite_and_planning_in_one_call() -> None:
    llm = FakeLLM(
        {
            "standalone_query": "比较 ToolExecutor 和 Evidence Gate 的职责",
            "sub_queries": [
                "ToolExecutor 的职责",
                "Evidence Gate 的职责",
            ],
            "filters": {"doc_type": "md", "unsupported": "drop"},
            "reason": "comparison targets",
        }
    )
    analyzer = QueryPreparationAnalyzer(llm=llm)

    result = analyzer.prepare("比较它们。", [], QueryIntent.COMPARISON)

    assert llm.calls == 1
    assert len(result.sub_queries) == 2
    assert result.filters == {"doc_type": "md"}


def test_prepare_rejects_empty_standalone_query() -> None:
    analyzer = QueryPreparationAnalyzer(
        llm=FakeLLM(
            {
                "standalone_query": "",
                "sub_queries": [],
                "filters": {},
                "reason": "invalid",
            }
        )
    )

    with pytest.raises(ValueError, match="standalone_query"):
        analyzer.prepare("问题", [], QueryIntent.KNOWLEDGE_QA)


@pytest.mark.parametrize("filters", [None, []])
def test_prepare_normalizes_empty_filter_variants(filters: object) -> None:
    analyzer = QueryPreparationAnalyzer(
        llm=FakeLLM(
            {
                "standalone_query": "ToolRegistry 的作用是什么？",
                "sub_queries": [],
                "filters": filters,
                "reason": None,
            }
        )
    )

    result = analyzer.prepare("ToolRegistry 的作用是什么？", [], QueryIntent.KNOWLEDGE_QA)

    assert result.filters == {}
    assert result.reason == ""


def test_prepare_falls_back_when_primary_model_returns_invalid_structure() -> None:
    primary = InvalidLLM({})
    fallback = FakeLLM(
        {
            "standalone_query": "valid fallback query",
            "sub_queries": ["target A", "target B"],
            "filters": {},
            "reason": "fallback",
        }
    )
    analyzer = QueryPreparationAnalyzer(llm=primary, fallback_llm=fallback)

    result = analyzer.prepare("compare A and B", [], QueryIntent.COMPARISON)

    assert result.standalone_query == "valid fallback query"
    assert result.sub_queries == ["target A", "target B"]
    assert primary.calls == 1
    assert fallback.calls == 1


def test_llm_client_supports_instance_specific_model_without_changing_default() -> None:
    default_client = LLMClient()
    preparation_client = LLMClient(model="fast-preparation-model")

    assert preparation_client.model == "fast-preparation-model"
    assert default_client.model != "fast-preparation-model"


def test_prepare_preserves_mixed_subtask_intent_suggestions() -> None:
    analyzer = QueryPreparationAnalyzer(
        llm=FakeLLM(
            {
                "standalone_query": "Summarize CP1 and compare it with CP2.",
                "sub_tasks": [
                    {"query": "Summarize CP1.", "suggested_intent": "summarization"},
                    {"query": "Compare CP1 with CP2.", "suggested_intent": "comparison"},
                ],
                "filters": {},
                "reason": "mixed task",
            }
        )
    )

    result = analyzer.prepare(
        "Summarize CP1 and compare it with CP2.", [], QueryIntent.COMPARISON
    )

    assert result.sub_queries == ["Summarize CP1.", "Compare CP1 with CP2."]
    assert [task.suggested_intent for task in result.sub_tasks] == [
        QueryIntent.SUMMARIZATION,
        QueryIntent.COMPARISON,
    ]
