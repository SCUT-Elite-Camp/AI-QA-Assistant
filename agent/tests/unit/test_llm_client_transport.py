import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from agent.errors.exceptions import LLMError
from agent.llm.llm_client import LLMClient

# Capture before the shared autouse fixture replaces product streaming.
PRODUCT_STREAM_CHAT = LLMClient.stream_chat


pytestmark = pytest.mark.no_storage


@pytest.mark.parametrize('model', ['qwen3.5-35b-a3b', 'deepseek-v4.1-flash'])
def test_shared_runtime_disables_thinking_by_default_but_preserves_opt_in(monkeypatch, model):
    from agent.config.settings import settings
    monkeypatch.setattr(settings, 'LLM_THINKING_MODE', '')
    assert LLMClient(model=model).enable_thinking is False
    assert LLMClient(model=model, enable_thinking=True).enable_thinking is True
    monkeypatch.setattr(settings, 'LLM_THINKING_MODE', 'enabled')
    assert LLMClient(model=model).enable_thinking is True


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


@pytest.mark.parametrize('failure', ['network', 'empty'])
def test_stream_retries_before_answer_but_never_saves_empty_answer(monkeypatch, failure):
    import requests
    from types import SimpleNamespace
    client = LLMClient(model='test')
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1 and failure == 'network':
            raise requests.ConnectionError('temporary TLS EOF')
        lines = ['data: [DONE]'] if len(calls) == 1 else ['data: '+json.dumps({'choices':[{'delta':{'content':'Complete answer'}}]}), 'data: [DONE]']
        return SimpleNamespace(status_code=200, iter_lines=lambda **kwargs:iter(lines), close=lambda:None)
    monkeypatch.setattr(client._session, 'post', post)
    assert list(PRODUCT_STREAM_CHAT(client,[{'role':'user','content':'Question'}])) == [{'content':'Complete answer','reasoning_content':''}]
    assert len(calls) == 2


def test_stream_does_not_retry_after_partial_answer(monkeypatch):
    import requests
    from types import SimpleNamespace
    client = LLMClient(model='test')
    calls = []
    def lines(**kwargs):
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':'Partial answer'}}]})
        raise requests.ConnectionError('connection interrupted')
    def post(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200,iter_lines=lines,close=lambda:None)
    monkeypatch.setattr(client._session,'post',post)
    stream = PRODUCT_STREAM_CHAT(client,[{'role':'user','content':'Question'}])
    assert next(stream)['content'] == 'Partial answer'
    with pytest.raises(LLMError,match='connection interrupted'):
        next(stream)
    assert len(calls) == 1


def test_empty_stream_rescues_from_non_stream_completion_without_duplicate_tokens(monkeypatch):
    from types import SimpleNamespace
    client = LLMClient(model='test')
    calls = []
    monkeypatch.setattr(client._session,'post',lambda *args,**kwargs: SimpleNamespace(status_code=200,iter_lines=lambda **kwargs:iter(['data: [DONE]']),close=lambda:None))
    def chat(messages, **kwargs):
        calls.append((messages,kwargs))
        return {'content':'Verified non-stream answer'}
    monkeypatch.setattr(client,'chat',chat)
    assert list(PRODUCT_STREAM_CHAT(client,[{'role':'user','content':'Question'}])) == [{'content':'Verified non-stream answer','reasoning_content':''}]
    assert len(calls) == 1
