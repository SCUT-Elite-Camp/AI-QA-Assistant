import json

import pytest

from agent.llm.base import BaseLLM
from agent.query import IntentClassifier, QueryIntent


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


def llm_intent(
    intent: str,
    *,
    confidence: float = 0.9,
    is_follow_up: bool = False,
    is_clarification_reply: bool = False,
    reason: str = "",
) -> dict:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "intent": intent,
                "confidence": confidence,
                "is_follow_up": is_follow_up,
                "is_clarification_reply": is_clarification_reply,
                "reason": reason,
            },
            ensure_ascii=False,
        ),
    }


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("CP2 的目标是什么？", QueryIntent.KNOWLEDGE_QA),
        ("帮我找 CP2 分工文档", QueryIntent.DOCUMENT_SEARCH),
        ("总结一下这份计划", QueryIntent.SUMMARIZATION),
        ("比较 CP1 和 CP2", QueryIntent.COMPARISON),
        ("你好", QueryIntent.CASUAL_CHAT),
        ("这个系统支持什么功能？", QueryIntent.SYSTEM_HELP),
        ("帮我修改银行账户余额", QueryIntent.UNSUPPORTED),
    ],
)
def test_classifier_supports_frozen_intent_taxonomy(
    query: str,
    intent: QueryIntent,
) -> None:
    classifier = IntentClassifier(llm=FakeLLM(llm_intent(intent.value)))

    result = classifier.classify(query, [])

    assert result.intent == intent
    assert result.confidence == 0.9


def test_classifier_returns_follow_up_flags() -> None:
    classifier = IntentClassifier(
        llm=FakeLLM(
            llm_intent(
                "knowledge_qa",
                is_follow_up=True,
                reason="The pronoun refers to Agent CP1 in history.",
            )
        )
    )

    result = classifier.classify(
        "它有哪些不足？",
        [
            {"role": "user", "content": "介绍 Agent CP1。"},
            {"role": "assistant", "content": "Agent CP1 是单轮 RAG。"},
        ],
    )

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.is_follow_up is True
    assert result.is_clarification_reply is False


def test_classifier_can_mark_possible_clarification_reply() -> None:
    classifier = IntentClassifier(
        llm=FakeLLM(
            llm_intent(
                "comparison",
                is_follow_up=True,
                is_clarification_reply=True,
            )
        )
    )

    result = classifier.classify(
        "Q1 和 CP2",
        [
            {
                "role": "assistant",
                "content": "Which objects should be compared?",
            }
        ],
    )

    assert result.intent == QueryIntent.COMPARISON
    assert result.is_follow_up is True
    assert result.is_clarification_reply is True


def test_prompt_contains_only_supported_history_messages() -> None:
    llm = FakeLLM(llm_intent("knowledge_qa"))
    classifier = IntentClassifier(llm=llm)

    classifier.classify(
        "继续",
        [
            {"role": "user", "content": "有效历史", "private": "ignored"},
            {"role": "tool", "content": "工具内部结果"},
            {"role": "assistant", "content": 123},
            "invalid",
        ],
    )

    assert llm.messages is not None
    payload = json.loads(llm.messages[1]["content"])
    assert payload == {
        "history": [{"role": "user", "content": "有效历史"}],
        "current_query": "继续",
    }


def test_markdown_json_response_is_accepted() -> None:
    llm = FakeLLM(
        {
            "content": (
                "```json\n"
                '{"intent":"comparison","confidence":0.95,'
                '"is_follow_up":false,"is_clarification_reply":false,'
                '"reason":"Two objects are compared."}\n'
                "```"
            )
        }
    )
    classifier = IntentClassifier(llm=llm)

    result = classifier.classify("比较 CP1 和 CP2", [])

    assert result.intent == QueryIntent.COMPARISON
    assert result.confidence == 0.95


@pytest.mark.parametrize(
    "response",
    [
        {"content": "not-json"},
        {"content": "[]"},
        {"content": '{"intent":"unknown","confidence":0.8}'},
        {"content": '{"intent":"knowledge_qa","confidence":1.1}'},
        {"content": '{"intent":"knowledge_qa","confidence":-0.1}'},
        {"content": '{"intent":"knowledge_qa"}'},
        {
            "content": (
                '{"intent":"knowledge_qa","confidence":0.8,'
                '"unexpected":"contract drift"}'
            )
        },
        {"content": None},
        {},
    ],
)
def test_invalid_model_response_uses_safe_fallback(response: dict) -> None:
    classifier = IntentClassifier(llm=FakeLLM(response))

    result = classifier.classify("当前问题", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence == 0.0
    assert result.is_follow_up is False
    assert result.is_clarification_reply is False
    assert result.reason == "intent_classification_failed"


def test_llm_error_uses_safe_fallback() -> None:
    classifier = IntentClassifier(
        llm=FakeLLM(error=RuntimeError("LLM unavailable"))
    )

    result = classifier.classify("当前问题", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence == 0.0
    assert result.reason == "intent_classification_failed"


def test_disabled_classifier_does_not_call_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    classifier = IntentClassifier(llm=llm, enabled=False)

    result = classifier.classify("当前问题", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence == 0.0
    assert result.reason == "query_understanding_disabled"
    assert llm.messages is None


def test_empty_query_does_not_call_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    classifier = IntentClassifier(llm=llm)

    result = classifier.classify("   ", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence == 0.0
    assert result.reason == "empty_query"
    assert llm.messages is None
