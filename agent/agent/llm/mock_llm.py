from agent.llm.base import BaseLLM


class MockLLM(BaseLLM):
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise

    def generate(self, prompt: str) -> str:
        if self.should_raise:
            raise RuntimeError("mock llm error")
        return "Q1 阶段需要完成简化版单轮 RAG Agent，包括 /api/chat、Mock Retrieval、Prompt Builder、Mock LLM 和 Answer Formatter 等最小闭环能力。[1]"

