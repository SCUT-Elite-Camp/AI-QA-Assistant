import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.config.settings import settings
from agent.errors.exceptions import LLMError
from agent.llm.base import BaseLLM


class LLMClient(BaseLLM):
    def generate(self, prompt: str) -> str:
        """Helper to generate a response for a single text prompt."""
        messages = [{"role": "user", "content": prompt}]
        msg = self.chat(messages)
        return (msg.get("content") or "").strip()

    def chat(self, messages: list[dict], tools: list[dict] = None, temperature: float = None, max_tokens: int = None, **kwargs) -> dict:
        """Calls the OpenAI-compatible chat/completions endpoint with messages and tools."""
        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Content-Type": "application/json",
        }
        if settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=settings.LLM_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        try:
            message = data["choices"][0]["message"]
            return message
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response format is invalid.") from exc

    def stream_chat(self, messages: list[dict], tools: list[dict] = None, temperature: float = None, max_tokens: int = None, **kwargs):
        """Streams chat completion deltas (content and reasoning_content) from OpenAI-compatible endpoint."""
        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Content-Type": "application/json",
        }
        if settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=settings.LLM_TIMEOUT) as response:
                for line_bytes in response:
                    line = line_bytes.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning_content") or ""
                            if content or reasoning:
                                yield {
                                    "content": content,
                                    "reasoning_content": reasoning,
                                }
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"LLM streaming request failed: {exc}") from exc
