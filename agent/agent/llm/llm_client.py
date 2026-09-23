import json
import time
import requests

from agent.config.settings import settings
from agent.errors.exceptions import LLMError
from agent.llm.base import BaseLLM


class LLMClient(BaseLLM):
    def __init__(
        self,
        *,
        model: str | None = None,
        enable_thinking: bool | None = None,
    ) -> None:
        self.model = model.strip() if isinstance(model, str) and model.strip() else settings.LLM_MODEL
        self.enable_thinking = enable_thinking
        self._session = requests.Session()
        # Do not inherit broken local environment proxy configurations unless explicit
        self._session.trust_env = False

    def generate(self, prompt: str) -> str:
        """Helper to generate a response for a single text prompt."""
        messages = [{"role": "user", "content": prompt}]
        msg = self.chat(messages)
        return (msg.get("content") or "").strip()

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict:
        """Calls the OpenAI-compatible chat/completions endpoint with messages and tools, with retry on 503/429."""
        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS,
        }
        if tools:
            payload["tools"] = tools
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking

        headers = {
            "Content-Type": "application/json",
        }
        if settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = self._session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=settings.LLM_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    try:
                        message = data["choices"][0]["message"]
                        return message
                    except (KeyError, IndexError, TypeError) as exc:
                        raise LLMError("LLM response format is invalid.") from exc

                # If 503 (High Demand) or 429 (Rate Limit), sleep and retry
                if resp.status_code in (429, 503, 500, 502) and attempt < max_retries - 1:
                    sleep_time = (attempt + 1) * 3
                    time.sleep(sleep_time)
                    continue

                raise LLMError(f"LLM API returned status {resp.status_code}: {resp.text}")
            except requests.RequestException as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)
                    continue
                raise LLMError(f"LLM request failed: {exc}") from exc

        if last_error:
            raise LLMError(f"LLM request failed after retries: {last_error}")
        raise LLMError("LLM request failed after retries.")

    def stream_chat(self, messages: list[dict], tools: list[dict] = None, temperature: float = None, max_tokens: int = None, **kwargs):
        """Streams chat completion deltas (content and reasoning_content) from OpenAI-compatible endpoint."""
        endpoint = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking

        headers = {
            "Content-Type": "application/json",
        }
        if settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

        try:
            resp = self._session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=settings.LLM_TIMEOUT,
                stream=True,
            )
            if resp.status_code != 200:
                raise LLMError(f"LLM API returned status {resp.status_code}: {resp.text}")

            for line in resp.iter_lines(decode_unicode=True):
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
                except json.JSONDecodeError:
                    continue
        except requests.RequestException as exc:
            raise LLMError(f"LLM streaming request failed: {exc}") from exc
