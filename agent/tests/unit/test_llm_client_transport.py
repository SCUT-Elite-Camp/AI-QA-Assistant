import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from agent.errors.exceptions import LLMError
from agent.llm.llm_client import LLMClient


pytestmark = pytest.mark.no_storage


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_transient_transport_failure_is_retried_once(monkeypatch) -> None:
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary TLS EOF")
        return _Response({"choices": []})

    monkeypatch.setattr("agent.llm.llm_client.urlopen", fake_urlopen)

    result = LLMClient._request_json(Request("https://example.com"))

    assert result == {"choices": []}
    assert calls == 2


def test_http_error_is_not_retried(monkeypatch) -> None:
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("agent.llm.llm_client.urlopen", fake_urlopen)

    with pytest.raises(LLMError, match="403"):
        LLMClient._request_json(Request("https://example.com"))

    assert calls == 1
