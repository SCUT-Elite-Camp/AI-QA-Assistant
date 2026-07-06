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

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        """Calls the OpenAI-compatible chat/completions endpoint with messages and tools."""
        if not settings.LLM_API_KEY:
            raise LLMError("LLM API key is not configured.")

        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
        if tools:
            payload["tools"] = tools

        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
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
