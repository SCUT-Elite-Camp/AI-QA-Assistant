from abc import ABC, abstractmethod


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict:
        raise NotImplementedError

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ):
        raise NotImplementedError

