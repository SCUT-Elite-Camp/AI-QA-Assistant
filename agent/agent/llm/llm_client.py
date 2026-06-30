import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.config.settings import settings
from agent.errors.exceptions import LLMError
from agent.llm.base import BaseLLM


class LLMClient(BaseLLM):
    def generate(self, prompt: str) -> str:
        if not settings.LLM_API_KEY:
            raise LLMError("LLM API key is not configured.")

        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
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
            answer = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response format is invalid.") from exc

        if not answer:
            raise LLMError("LLM response is empty.")

        return answer
