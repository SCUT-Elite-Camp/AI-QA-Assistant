"""Schema-constrained chat completion adapters for the Wiki pipeline."""

from __future__ import annotations

import json
import os
import sys
import time
from http.client import IncompleteRead, RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def deepseek_api_key_from_environment() -> str:
    """Read a process key, or the Windows user variable set by PowerShell."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key or sys.platform != "win32":
        return key
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            value, _value_type = winreg.QueryValueEx(handle, "DEEPSEEK_API_KEY")
    except FileNotFoundError:
        return ""
    return str(value).strip()


class OpenAICompatibleJsonLLM:
    def __init__(
        self, *, base_url: str, model: str, api_key: str = "local-knowledge-graph",
        timeout_seconds: float = 300.0, allow_external: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        if not self.model:
            raise ValueError("knowledge extraction model is required")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "localhost", "127.0.0.1", "::1",
        }:
            if not allow_external:
                raise ValueError("private knowledge extraction requires a local endpoint")

    def complete(
        self, *, system: str, user: dict[str, Any], schema_name: str,
        schema: dict[str, Any], max_tokens: int = 2400,
    ) -> dict[str, Any]:
        payload = self._request({
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": schema,
            }},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
        })
        return self._parse_content(payload)

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("knowledge model response must be an object")
        return payload

    @staticmethod
    def _parse_content(payload: dict[str, Any]) -> dict[str, Any]:
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            value = content
        else:
            text = str(content).strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].lstrip()
            value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("knowledge model must return a JSON object")
        return value


class DeepSeekJsonLLM(OpenAICompatibleJsonLLM):
    """DeepSeek Chat JSON-mode adapter for explicitly authorised external probes."""

    ENDPOINT = "https://api.deepseek.com"

    def __init__(
        self, *, api_key: str, model: str = "deepseek-v4-pro",
        timeout_seconds: float = 300.0, max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("DEEPSEEK_API_KEY is required")
        if model not in {"deepseek-v4-pro", "deepseek-v4-flash"}:
            raise ValueError("unsupported DeepSeek text model")
        if max_retries < 0 or retry_backoff_seconds < 0:
            raise ValueError("DeepSeek retry bounds must be non-negative")
        super().__init__(
            base_url=self.ENDPOINT, model=model, api_key=api_key.strip(),
            timeout_seconds=timeout_seconds, allow_external=True,
        )
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Retry only transient transport and service failures."""
        for attempt in range(self.max_retries + 1):
            try:
                return super()._request(body)
            except HTTPError as exc:
                retryable = exc.code in {408, 429} or 500 <= exc.code < 600
                if not retryable or attempt >= self.max_retries:
                    raise
            except (IncompleteRead, RemoteDisconnected, TimeoutError, ConnectionResetError, URLError):
                if attempt >= self.max_retries:
                    raise
            time.sleep(self.retry_backoff_seconds * (2 ** attempt))
        raise AssertionError("unreachable DeepSeek retry state")

    def complete(
        self, *, system: str, user: dict[str, Any], schema_name: str,
        schema: dict[str, Any], max_tokens: int = 2400,
    ) -> dict[str, Any]:
        payload = self._request({
            "model": self.model, "thinking": {"type": "disabled"},
            "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + " Return only a JSON object matching the supplied schema."},
                {"role": "user", "content": json.dumps({
                    **user, "output_schema_name": schema_name, "output_json_schema": schema,
                }, ensure_ascii=False)},
            ],
        })
        choice = payload["choices"][0]
        usage = payload.get("usage") or {}
        for key in self.usage:
            self.usage[key] += int(usage.get(key) or 0)
        finish_reason = choice.get("finish_reason")
        if finish_reason not in (None, "stop"):
            raise ValueError(f"DeepSeek response did not finish normally: {finish_reason}")
        return self._parse_content(payload)
