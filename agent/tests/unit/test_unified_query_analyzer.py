import json

import pytest

from agent.llm.base import BaseLLM
from agent.query import QueryIntent, UnifiedQueryAnalyzer


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


def _payload(**updates: object) -> dict:
    value = {
        "intent": "knowledge_qa",
        "confidence": 0.94,
        "is_follow_up": False,
        "is_clarification_reply": False,
        "needs_clarification": False,
        "clarification_question": "",
        "ambiguity_reason": "sufficient context",
        "standalone_query": "What does ToolRegistry do?",
        "sub_queries": [],
        "filters": {},
    }
    value.update(updates)
    return value


def test_analyze_returns_all_query_fields_in_one_llm_call() -> None:
    llm = FakeLLM(_payload(filters={"doc_type": "md", "unknown": "drop"}))
    analyzer = UnifiedQueryAnalyzer(llm=llm)

    result = analyzer.analyze("What does it do?", [])

    assert llm.calls == 1
    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence == 0.94
    assert result.standalone_query == "What does ToolRegistry do?"
    assert result.filters == {"doc_type": "md"}


def test_clarification_clears_retrieval_plan() -> None:
    analyzer = UnifiedQueryAnalyzer(
        llm=FakeLLM(
            _payload(
                needs_clarification=True,
                clarification_question="Which versions should be compared?",
                standalone_query="invented rewrite",
                sub_queries=["one", "two"],
                filters={"doc_type": "md"},
            )
        )
    )

    result = analyzer.analyze("Compare them.", [])

    assert result.needs_clarification is True
    assert result.standalone_query == "Compare them."
    assert result.sub_queries == []
    assert result.filters == {}


def test_missing_clarification_question_is_rejected() -> None:
    analyzer = UnifiedQueryAnalyzer(
        llm=FakeLLM(_payload(needs_clarification=True))
    )

    with pytest.raises(ValueError, match="clarification_question"):
        analyzer.analyze("Compare them.", [])


def test_named_confidence_is_normalized_for_model_compatibility() -> None:
    analyzer = UnifiedQueryAnalyzer(llm=FakeLLM(_payload(confidence="high")))

    result = analyzer.analyze("What does ToolRegistry do?", [])

    assert result.confidence == 0.9


def test_null_optional_text_is_normalized_for_model_compatibility() -> None:
    analyzer = UnifiedQueryAnalyzer(
        llm=FakeLLM(
            _payload(clarification_question=None, ambiguity_reason=None)
        )
    )

    result = analyzer.analyze("What does ToolRegistry do?", [])

    assert result.clarification_question == ""
    assert result.ambiguity_reason == ""
