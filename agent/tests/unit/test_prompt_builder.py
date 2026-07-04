from agent.prompt.prompt_builder import PromptBuilder


def test_prompt_contains_query_context_and_constraints() -> None:
    prompt = PromptBuilder().build(query="测试问题", context="[1]\nchunk_text: 测试上下文")

    assert "测试问题" in prompt
    assert "测试上下文" in prompt
    assert "不得编造" in prompt
    assert "引用编号只能使用检索上下文中真实存在的编号" in prompt
    assert "不要猜测" in prompt
