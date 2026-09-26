# agent/tests/helpers.py
"""Shared test helpers and mocks for Agent test suite."""
import json
from agent.llm.base import BaseLLM


class FakeLLM(BaseLLM):
    """Hermetic mock LLM for unit tests."""

    def __init__(
        self,
        response: dict | None = None,
        error: Exception | None = None,
        payload: dict | None = None,
    ):
        if payload is not None:
            self.response = {"content": json.dumps(payload, ensure_ascii=False)}
        elif response is not None and "content" not in response and "role" not in response:
            # response passed positionally as raw payload dict
            self.response = {"content": json.dumps(response, ensure_ascii=False)}
        else:
            self.response = response or {}
        self.error = error
        self.messages: list[dict] | None = None
        self.calls = 0

    def generate(self, prompt: str) -> str:
        return ""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls += 1
        self.messages = messages
        if self.error:
            raise self.error
        return self.response
