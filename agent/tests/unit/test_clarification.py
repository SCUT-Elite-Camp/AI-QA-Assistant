import json

import pytest

from agent.llm.base import BaseLLM
from agent.query import Clarifier
from agent.schemas.common import StatusCode


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


def llm_decision(
    needs_clarification: bool,
    question: str = "",
    reason: str = "",
) -> dict:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "needs_clarification": needs_clarification,
                "question": question,
                "reason": reason,
            },
            ensure_ascii=False,
        ),
    }


def test_ambiguous_query_requires_clarification() -> None:
    clarifier = Clarifier(
        llm=FakeLLM(
            llm_decision(
                True,
                "请问你指的是 Agent 层、Web 层，还是整个项目？",
                "问题缺少明确的业务对象",
            )
        )
    )

    decision = clarifier.evaluate("它有什么问题？", [])

    assert decision.needs_clarification is True
    assert decision.question == "请问你指的是 Agent 层、Web 层，还是整个项目？"
    assert "业务对象" in decision.reason


def test_clear_short_query_does_not_require_clarification() -> None:
    clarifier = Clarifier(
        llm=FakeLLM(llm_decision(False, reason="RAG 是明确的专业术语"))
    )

    decision = clarifier.evaluate("什么是 RAG？", [])

    assert decision.needs_clarification is False
    assert decision.question == ""


def test_history_can_resolve_reference_without_clarification() -> None:
    llm = FakeLLM(llm_decision(False, reason="历史已经明确“它”指 Agent 层"))
    clarifier = Clarifier(llm=llm)

    decision = clarifier.evaluate(
        "它有哪些不足？",
        [
            {"role": "user", "content": "介绍 Agent 层的 Q1 成果"},
            {"role": "assistant", "content": "Agent 层完成了单轮 RAG。"},
        ],
    )

    assert decision.needs_clarification is False
    assert decision.question == ""


def test_false_decision_discards_unneeded_question() -> None:
    clarifier = Clarifier(
        llm=FakeLLM(
            llm_decision(False, question="这段内容不应该返回", reason="问题明确")
        )
    )

    decision = clarifier.evaluate("什么是 RAG？", [])

    assert decision.question == ""


def test_prompt_contains_only_supported_history_messages() -> None:
    llm = FakeLLM(llm_decision(False))
    clarifier = Clarifier(llm=llm)

    clarifier.evaluate(
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
                '{"needs_clarification":true,'
                '"question":"请明确项目范围。","reason":"范围不明确"}\n'
                "```"
            )
        }
    )
    clarifier = Clarifier(llm=llm)

    decision = clarifier.evaluate("有什么问题？", [])

    assert decision.needs_clarification is True
    assert decision.question == "请明确项目范围。"


@pytest.mark.parametrize(
    "response",
    [
        {"content": "not-json"},
        {"content": "[]"},
        {"content": '{"needs_clarification":true,"question":""}'},
        {"content": '{"question":"缺少判断字段"}'},
        {"content": None},
        {},
    ],
)
def test_invalid_model_response_continues_without_clarification(
    response: dict,
) -> None:
    clarifier = Clarifier(llm=FakeLLM(response))

    decision = clarifier.evaluate("当前问题", [])

    assert decision.needs_clarification is False
    assert decision.question == ""
    assert decision.reason == "clarification_check_failed"


def test_llm_error_continues_without_clarification() -> None:
    clarifier = Clarifier(llm=FakeLLM(error=RuntimeError("LLM unavailable")))

    decision = clarifier.evaluate("当前问题", [])

    assert decision.needs_clarification is False
    assert decision.reason == "clarification_check_failed"


def test_disabled_clarifier_does_not_call_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    clarifier = Clarifier(llm=llm, enabled=False)

    decision = clarifier.evaluate("当前问题", [])

    assert decision.needs_clarification is False
    assert decision.reason == "clarification_disabled"
    assert llm.messages is None


def test_empty_query_is_left_for_request_validation() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    clarifier = Clarifier(llm=llm)

    decision = clarifier.evaluate("   ", [])

    assert decision.needs_clarification is False
    assert decision.reason == "empty_query"
    assert llm.messages is None


def test_clarification_status_code_is_available() -> None:
    assert StatusCode.CLARIFICATION_REQUIRED == "clarification_required"
