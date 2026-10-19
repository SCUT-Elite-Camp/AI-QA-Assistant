import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from agent.errors.exceptions import LLMError
from agent.llm.llm_client import LLMClient

# Capture before the shared autouse fixture replaces product streaming.
PRODUCT_STREAM_CHAT = LLMClient.stream_chat
PRODUCT_CHAT = LLMClient.chat


def test_native_control_choice_and_remaining_deadline_reach_transport(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{
            'tool_calls':[{'function':{'name':'prepare_answer','arguments':'{}'}}]}}]})
    client=LLMClient(fallback_models=(),attempts_per_model=1,retry_delay_seconds=0)
    monkeypatch.setattr(client._session,'post',post)
    PRODUCT_CHAT(client,[{'role':'user','content':'What is the release status?'}],
        tools=[{'type':'function','function':{'name':'prepare_answer'}}],tool_choice='required',timeout_seconds=1.25)
    assert len(calls)==1 and calls[0]['json']['tool_choice']=='required' and calls[0]['timeout']==1.25


def test_groq_rejected_tool_is_typed_without_releasing_failed_generation(monkeypatch):
    from types import SimpleNamespace
    from agent.config.settings import settings
    from agent.errors.exceptions import LLMToolCallValidationError
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://api.groq.com/openai/v1')
    client = LLMClient(fallback_models=(), attempts_per_model=1)
    response = SimpleNamespace(status_code=400,
        json=lambda: {'error': {'code': 'tool_use_failed', 'failed_generation': 'private draft'}},
        text='private draft')
    monkeypatch.setattr(client._session, 'post', lambda *args, **kwargs: response)
    with pytest.raises(LLMToolCallValidationError) as error:
        PRODUCT_CHAT(client, [{'role': 'user', 'content': 'q'}], tools=[{'type': 'function'}])
    assert 'private draft' not in str(error.value)


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('response_format', [None, {'type': 'json_object'}])
def test_structured_format_reaches_provider_in_one_request(monkeypatch, stream, response_format):
    from types import SimpleNamespace
    calls = []
    content = '{"answer":"ok","claims":[]}'
    def post(*args, **kwargs):
        calls.append(kwargs['json'])
        return SimpleNamespace(status_code=200, encoding='utf-8',
            json=lambda: {'choices': [{'message': {'content': content}}]},
            iter_lines=lambda **kwargs: iter(['data: ' + json.dumps({'choices': [{'delta': {'content': content}}]}), 'data: [DONE]']),
            close=lambda: None)
    client = LLMClient(model='fixed-fast', fallback_models=(), attempts_per_model=1)
    monkeypatch.setattr(client._session, 'post', post)
    kwargs = {'response_format': response_format} if response_format else {}
    if stream:
        assert ''.join(item['content'] for item in PRODUCT_STREAM_CHAT(client, [{'role': 'user', 'content': 'JSON please'}], **kwargs)) == content
    else:
        assert PRODUCT_CHAT(client, [{'role': 'user', 'content': 'JSON please'}], **kwargs)['content'] == content
    assert len(calls) == 1
    assert calls[0].get('response_format') == response_format


def test_fast_transport_does_not_retry_or_fall_back_after_failure(monkeypatch):
    import requests
    client = LLMClient(model='fixed-fast', fallback_models=(), attempts_per_model=1, retry_delay_seconds=0)
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs['json']['model'])
        raise requests.ConnectionError('provider unavailable')
    monkeypatch.setattr(client._session, 'post', fail)
    with pytest.raises(LLMError):
        PRODUCT_CHAT(client, [{'role': 'user', 'content': 'Question'}])
    assert calls == ['fixed-fast']
    calls.clear()
    with pytest.raises(LLMError):
        list(PRODUCT_STREAM_CHAT(client, [{'role': 'user', 'content': 'Question'}]))
    assert calls == ['fixed-fast']


def test_empty_fast_stream_does_not_start_nonstream_generation(monkeypatch):
    client = LLMClient(model='fixed-fast', fallback_models=(), attempts_per_model=1, retry_delay_seconds=0)
    calls = []
    def empty(*args, **kwargs):
        calls.append(kwargs)
        return type('Response', (), {'status_code': 200, 'iter_lines': lambda *args, **kwargs: iter(['data: [DONE]']), 'close': lambda *args: None})()
    monkeypatch.setattr(client._session, 'post', empty)
    monkeypatch.setattr(client, 'chat', lambda *args, **kwargs: pytest.fail('Second generation'))
    with pytest.raises(LLMError):
        list(PRODUCT_STREAM_CHAT(client, [{'role': 'user', 'content': 'Question'}]))
    assert len(calls) == 1


pytestmark = pytest.mark.no_storage


@pytest.mark.parametrize('enabled,effort', [(False, 'low'), (True, 'high')])
def test_groq_gpt_oss_translates_mode_without_vendor_thinking_fields(monkeypatch, enabled, effort):
    from agent.config.settings import settings
    from agent.llm.provider_options import apply_provider_options
    monkeypatch.setattr(settings, 'LLM_REASONING_EFFORT', 'high')
    payload = {'model': 'openai/gpt-oss-20b', 'enable_thinking': enabled,
               'thinking_budget': 2048, 'reasoning_format': 'hidden', 'max_tokens': 3000}
    result = apply_provider_options(payload, 'https://api.groq.com/openai/v1')
    assert result == {'model': payload['model'], 'reasoning_effort': effort, 'max_completion_tokens': 3000}
    assert payload['max_tokens'] == 3000


def test_groq_fast_and_thinking_clients_select_their_configured_effort(monkeypatch):
    from agent.config.settings import settings
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://api.groq.com/openai/v1')
    monkeypatch.setattr(settings, 'ANSWER_FAST_MODEL', 'openai/gpt-oss-20b')
    monkeypatch.setattr(settings, 'ANSWER_FAST_MODEL_THINKING', False)
    monkeypatch.setattr(settings, 'LLM_THINKING_MODE', 'enabled')
    assert LLMClient(model='openai/gpt-oss-20b').enable_thinking is False
    assert LLMClient(model='openai/gpt-oss-120b').enable_thinking is True
    from agent.llm.provider_options import apply_provider_options
    # The dated-answer validator calls the shared boundary without a mode flag.
    assert apply_provider_options({'model': settings.ANSWER_FAST_MODEL}, settings.LLM_API_BASE)['reasoning_effort'] == 'low'


def test_groq_failure_does_not_route_to_unrequested_fallback_models(monkeypatch):
    from types import SimpleNamespace
    from agent.config.settings import settings
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://api.groq.com/openai/v1')
    calls = []
    client = LLMClient(model='openai/gpt-oss-20b', attempts_per_model=1, retry_delay_seconds=0)
    def post(*args, **kwargs):
        calls.append(kwargs['json']['model'])
        return SimpleNamespace(status_code=503, text='unavailable')
    monkeypatch.setattr(client._session, 'post', post)
    with pytest.raises(LLMError):
        PRODUCT_CHAT(client, [{'role': 'user', 'content': 'Question'}])
    assert calls == ['openai/gpt-oss-20b']


def test_gemini_payload_removes_unsupported_vendor_thinking_fields():
    from agent.llm.provider_options import apply_provider_options
    payload = {'model': 'gemini-3.5-flash-lite', 'messages': [{'role': 'user', 'content': 'Question'}],
               'thinking': {'type': 'disabled'}, 'enable_thinking': False, 'thinking_budget': 0}
    result = apply_provider_options(payload, 'https://generativelanguage.googleapis.com/v1beta/openai/')
    assert result == {'model': payload['model'], 'messages': payload['messages']}
    assert 'thinking' in payload


@pytest.mark.parametrize('model', ['qwen3.5-35b-a3b', 'deepseek-v4.1-flash'])
def test_llm_client_disables_thinking_by_default_but_preserves_opt_in(monkeypatch, model):
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


def test_openrouter_fast_stream_uses_reasoning_flag_and_normalizes_delta(monkeypatch):
    from types import SimpleNamespace
    from agent.config.settings import settings
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://openrouter.ai/api/v1')
    monkeypatch.setattr(settings, 'ANSWER_FAST_MODEL', 'nvidia/lightning:free')
    monkeypatch.setattr(settings, 'ANSWER_FAST_MODEL_THINKING', False)
    monkeypatch.setattr(settings, 'LLM_THINKING_MODE', 'enabled')
    client = LLMClient(model=settings.ANSWER_FAST_MODEL)
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs['json'])
        lines = [
            'data: '+json.dumps({'choices':[{'delta':{'reasoning':'Provider reasoning'}}]}),
            'data: '+json.dumps({'choices':[{'delta':{'content':'4'}}]}),
            'data: [DONE]',
        ]
        return SimpleNamespace(status_code=200, iter_lines=lambda **kwargs: iter(lines), close=lambda:None)
    monkeypatch.setattr(client._session, 'post', post)
    result = list(PRODUCT_STREAM_CHAT(client, [{'role':'user','content':'2+2?'}]))
    assert calls[0]['reasoning'] == {'enabled': False}
    assert 'enable_thinking' not in calls[0]
    assert result[0]['reasoning_content'] == 'Provider reasoning'
    assert result[1]['content'] == '4'


def test_openrouter_research_translates_thinking_and_reserves_answer_budget(monkeypatch):
    from agent.config.settings import settings
    from agent.llm.provider_options import apply_provider_options
    monkeypatch.setattr(settings, 'LLM_REASONING_EFFORT', 'medium')
    payload = {'thinking': {'type':'enabled'}, 'max_tokens':1200}
    result = apply_provider_options(payload, 'https://openrouter.ai/api/v1')
    assert result['reasoning'] == {'enabled':True, 'effort':'medium'}
    assert result['max_tokens'] >= 4096
    assert 'thinking' not in result
    assert payload['max_tokens'] == 1200
