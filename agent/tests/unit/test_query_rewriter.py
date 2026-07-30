import json

import pytest

from agent.llm.base import BaseLLM
from agent.query import QueryRewriter


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


def llm_json(rewritten_query: str, reason: str = "") -> dict:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "rewritten_query": rewritten_query,
                "reason": reason,
            },
            ensure_ascii=False,
        ),
    }


def test_rewrite_resolves_reference_from_history() -> None:
    llm = FakeLLM(
        llm_json(
            "Agent 层 Q1 阶段当前实现存在哪些限制和不足？",
            "结合历史补全“它”的指代对象",
        )
    )
    rewriter = QueryRewriter(llm=llm)

    result = rewriter.rewrite(
        "那它有哪些不足？",
        [
            {"role": "user", "content": "介绍 Agent 层的 Q1 成果"},
            {"role": "assistant", "content": "Agent 层完成了单轮 RAG 流程。"},
        ],
    )

    assert result.original_query == "那它有哪些不足？"
    assert result.rewritten_query == "Agent 层 Q1 阶段当前实现存在哪些限制和不足？"
    assert result.changed is True
    assert "指代" in result.reason


def test_clear_query_can_remain_unchanged() -> None:
    query = "什么是 RAG？"
    rewriter = QueryRewriter(llm=FakeLLM(llm_json(query, "问题已经明确")))

    result = rewriter.rewrite(query, [])

    assert result.original_query == query
    assert result.rewritten_query == query
    assert result.changed is False


def test_rewrite_preserves_technical_terms() -> None:
    rewritten = "ToolRegistry.to_openai_schemas() 返回什么结构？"
    rewriter = QueryRewriter(llm=FakeLLM(llm_json(rewritten)))

    result = rewriter.rewrite("这个接口返回什么？", [
        {
            "role": "assistant",
            "content": "刚才讨论的是 ToolRegistry.to_openai_schemas()。",
        }
    ])

    assert "ToolRegistry.to_openai_schemas()" in result.rewritten_query


def test_prompt_contains_only_supported_history_messages() -> None:
    llm = FakeLLM(llm_json("重写结果"))
    rewriter = QueryRewriter(llm=llm)

    rewriter.rewrite(
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
                '{"rewritten_query":"Agent 层有哪些问题？","reason":"补全范围"}\n'
                "```"
            )
        }
    )
    rewriter = QueryRewriter(llm=llm)

    result = rewriter.rewrite("有哪些问题？", [])

    assert result.rewritten_query == "Agent 层有哪些问题？"
    assert result.changed is True


@pytest.mark.parametrize(
    "response",
    [
        {"content": "not-json"},
        {"content": "[]"},
        {"content": '{"rewritten_query":""}'},
        {"content": None},
        {},
    ],
)
def test_invalid_model_response_falls_back_to_original_query(response: dict) -> None:
    rewriter = QueryRewriter(llm=FakeLLM(response))

    result = rewriter.rewrite("  原始问题  ", [])

    assert result.original_query == "  原始问题  "
    assert result.rewritten_query == "原始问题"
    assert result.changed is False
    assert result.reason == "rewrite_failed"


def test_llm_error_falls_back_to_original_query() -> None:
    rewriter = QueryRewriter(llm=FakeLLM(error=RuntimeError("LLM unavailable")))

    result = rewriter.rewrite("原始问题", [])

    assert result.rewritten_query == "原始问题"
    assert result.changed is False
    assert result.reason == "rewrite_failed"


def test_disabled_rewriter_does_not_call_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    rewriter = QueryRewriter(llm=llm, enabled=False)

    result = rewriter.rewrite("原始问题", [])

    assert result.rewritten_query == "原始问题"
    assert result.reason == "query_rewrite_disabled"
    assert llm.messages is None


def test_empty_query_does_not_call_llm() -> None:
    llm = FakeLLM(error=AssertionError("LLM must not be called"))
    rewriter = QueryRewriter(llm=llm)

    result = rewriter.rewrite("   ", [])

    assert result.original_query == "   "
    assert result.rewritten_query == ""
    assert result.changed is False
    assert result.reason == "empty_query"
    assert llm.messages is None
