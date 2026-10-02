from __future__ import annotations

import json
from http.client import IncompleteRead, RemoteDisconnected
from unittest.mock import patch

import pytest

from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_deepseek_adapter_uses_official_endpoint_json_mode_and_counts_tokens() -> None:
    client = DeepSeekJsonLLM(api_key="test-secret", model="deepseek-v4-pro")
    observed = {}

    def fake_urlopen(request, *, timeout):
        observed["url"] = request.full_url
        observed["body"] = json.loads(request.data)
        observed["timeout"] = timeout
        return _Response({
            "choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"ok"}'}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 4, "total_tokens": 21},
        })

    with patch("pipeline.wiki.llm.urlopen", side_effect=fake_urlopen):
        result = client.complete(system="Read Evidence.", user={"evidence_text": "private"},
                                 schema_name="unit", schema={"type": "object"})

    assert result == {"summary": "ok"}
    assert observed["url"] == "https://api.deepseek.com/chat/completions"
    assert observed["body"]["response_format"] == {"type": "json_object"}
    assert observed["body"]["thinking"] == {"type": "disabled"}
    assert observed["body"]["messages"][1]["content"].find('"output_json_schema"') >= 0
    assert client.usage == {"prompt_tokens": 17, "completion_tokens": 4, "total_tokens": 21}


def test_deepseek_adapter_rejects_missing_key_or_unapproved_model() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        DeepSeekJsonLLM(api_key="")
    with pytest.raises(ValueError, match="unsupported"):
        DeepSeekJsonLLM(api_key="test-secret", model="deepseek-chat")


def test_process_environment_key_is_preferred(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "  test-secret  ")
    assert deepseek_api_key_from_environment() == "test-secret"


def test_deepseek_adapter_rejects_truncated_generation() -> None:
    client = DeepSeekJsonLLM(api_key="test-secret")
    payload = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}}
    with patch("pipeline.wiki.llm.urlopen", return_value=_Response(payload)):
        with pytest.raises(ValueError, match="did not finish normally: length"):
            client.complete(system="", user={}, schema_name="unit", schema={"type": "object"})
    assert client.usage["total_tokens"] == 18


def test_deepseek_adapter_retries_transient_disconnect() -> None:
    client = DeepSeekJsonLLM(
        api_key="test-secret", max_retries=2, retry_backoff_seconds=0,
    )
    response = _Response({
        "choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"ok"}'}}],
        "usage": {},
    })
    with patch(
            "pipeline.wiki.llm.urlopen",
        side_effect=[RemoteDisconnected("temporary"), response],
    ) as mocked:
        assert client.complete(system="", user={}, schema_name="unit", schema={}) == {"summary": "ok"}
    assert mocked.call_count == 2


def test_deepseek_adapter_retries_incomplete_response_body() -> None:
    client = DeepSeekJsonLLM(api_key="test-secret", max_retries=1, retry_backoff_seconds=0)
    response = _Response({
        "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
        "usage": {},
    })
    with patch("pipeline.wiki.llm.urlopen", side_effect=[IncompleteRead(b""), response]) as mocked:
        assert client.complete(system="", user={}, schema_name="unit", schema={}) == {}
    assert mocked.call_count == 2


def test_deepseek_adapter_does_not_retry_non_transient_parse_error() -> None:
    client = DeepSeekJsonLLM(
        api_key="test-secret", max_retries=2, retry_backoff_seconds=0,
    )
    with patch("pipeline.wiki.llm.urlopen", return_value=_Response({"not": "a completion"})) as mocked:
        with pytest.raises(KeyError):
            client.complete(system="", user={}, schema_name="unit", schema={})
    assert mocked.call_count == 1
