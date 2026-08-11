from abc import ABC, abstractmethod


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] = None, temperature: float = None, max_tokens: int = None, **kwargs) -> dict:
        raise NotImplementedError

