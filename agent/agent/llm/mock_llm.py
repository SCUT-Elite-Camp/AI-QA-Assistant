from agent.llm.base import BaseLLM


class MockLLM(BaseLLM):
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise

    def generate(self, prompt: str) -> str:
        if self.should_raise:
            raise RuntimeError("mock llm error")

        try:
            parts = prompt.split("检索上下文：")
            if len(parts) > 1:
                context = parts[1].split("严格约束：")[0].strip()
                if context:
                    return context
        except Exception:
            pass

        return "未能检索到相关上下文。"
