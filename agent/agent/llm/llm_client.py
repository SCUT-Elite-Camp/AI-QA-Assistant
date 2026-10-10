import json
import os
import time
import requests

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.config.settings import settings
from agent.errors.exceptions import LLMError
from agent.llm.base import BaseLLM


class LLMClient(BaseLLM):
    def __init__(
        self,
        *,
        model: str | None = None,
        enable_thinking: bool | None = None,
        fallback_models: tuple[str, ...] | None = None,
        attempts_per_model: int = 2,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        if attempts_per_model < 1:
            raise ValueError("attempts_per_model must be at least 1")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")

        self.model = model.strip() if isinstance(model, str) and model.strip() else settings.LLM_MODEL
        self.enable_thinking = enable_thinking
        if enable_thinking is None and self.model.lower().startswith(('qwen3', 'qwen-flash', 'qwen-turbo', 'deepseek')):
            self.enable_thinking = settings.LLM_THINKING_MODE == 'enabled'
        self.fallback_models = fallback_models
        self.attempts_per_model = attempts_per_model
        self.retry_delay_seconds = retry_delay_seconds
        self._session = requests.Session()
        proxy = os.getenv("LLM_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if proxy:
            self._session.proxies.update({"http": proxy, "https": proxy})
        else:
            self._session.trust_env = True

    def close(self) -> None:
        """Release the underlying HTTP connection pool when the client is request-scoped."""
        self._session.close()

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

        candidate_models = [self.model]
        fallback_models = self.fallback_models
        if fallback_models is None:
            fallback_models = (
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite-preview",
                "gemma-4-26b-a4b-it",
            )
        for fallback in fallback_models:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        last_error = None
        for current_model in candidate_models:
            payload["model"] = current_model
            for attempt in range(self.attempts_per_model):
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

                    # If 429 / 503 / 404, retry or try next model
                    if resp.status_code in (429, 503, 500, 502, 404):
                        last_error = LLMError(f"LLM API returned status {resp.status_code} for {current_model}: {resp.text}")
                        if self.retry_delay_seconds:
                            time.sleep(self.retry_delay_seconds)
                        continue

                    raise LLMError(f"LLM API returned status {resp.status_code}: {resp.text}")
                except requests.RequestException as exc:
                    last_error = exc
                    if self.retry_delay_seconds:
                        time.sleep(self.retry_delay_seconds)
                    continue

        if last_error:
            raise LLMError(f"LLM request failed across candidate models: {last_error}")
        raise LLMError("LLM request failed.")

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

        answer_emitted = False
        for attempt in range(2):
            try:
                yield from self._stream_response(endpoint, payload, headers)
                return
            except requests.RequestException as exc:
                # Retrying after answer tokens were delivered would duplicate
                # or splice two independently generated answers.
                answer_emitted = getattr(exc, 'answer_emitted', False)
                if attempt == 0 and not answer_emitted:
                    continue
                if not answer_emitted and str(exc) == 'LLM stream produced no answer content':
                    # Some compatible providers finish a stream without any
                    # content deltas. A non-stream response is safe here because
                    # no answer body has been exposed or stored yet.
                    message = self.chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)
                    content = message.get('content') or ''
                    if isinstance(content, str) and content.strip():
                        yield {'content':content,'reasoning_content':''}
                        return
                raise LLMError(f"LLM streaming request failed: {exc}") from exc

    def _stream_response(self, endpoint: str, payload: dict, headers: dict):
        answer_emitted = False
        resp = None
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
                            answer_emitted = answer_emitted or bool(content)
                            yield {
                                "content": content,
                                "reasoning_content": reasoning,
                            }
                except json.JSONDecodeError:
                    continue
            if not answer_emitted:
                raise requests.ConnectionError('LLM stream produced no answer content')
        except requests.RequestException as exc:
            exc.answer_emitted = answer_emitted
            raise
        finally:
            if resp is not None and callable(getattr(resp, 'close', None)):
                resp.close()

    @staticmethod
    def _request_json(request: Request) -> dict:
        """Retry one transient transport failure, never deterministic HTTP errors."""
        for attempt in range(2):
            try:
                with urlopen(request, timeout=settings.LLM_TIMEOUT) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                # OpenAI-compatible providers return the actionable error code
                # in the response body. Preserve a bounded copy without
                # exposing request credentials.
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:2000]
                except Exception:
                    detail = ""
                suffix = f"; response={detail}" if detail else ""
                raise LLMError(f"LLM request failed: {exc}{suffix}") from exc
            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM request failed: {exc}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == 0:
                    continue
                raise LLMError(f"LLM request failed: {exc}") from exc

        raise LLMError("LLM request failed after transient retry.")
