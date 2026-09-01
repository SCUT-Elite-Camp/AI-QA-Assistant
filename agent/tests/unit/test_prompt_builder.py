from agent.prompt.prompt_builder import PromptBuilder
from agent.prompt.templates import ANSWER_RULES


def test_prompt_contains_query_context_and_constraints() -> None:
    prompt = PromptBuilder().build(
        query="测试问题",
        context="[1]\nchunk_text: 测试上下文",
    )

    assert "测试问题" in prompt
    assert "测试上下文" in prompt
    assert "Never invent facts" in prompt
    assert "citation numbers that actually exist" in prompt
    assert "instead of guessing" in prompt


def test_answer_rules_preserve_technical_identifiers() -> None:
    assert "preserve exact identifiers" in ANSWER_RULES
    assert "field names" in ANSWER_RULES
    assert "status values" in ANSWER_RULES
