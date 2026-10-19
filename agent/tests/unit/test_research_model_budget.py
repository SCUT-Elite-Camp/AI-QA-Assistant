"""Completion exhaustion must stage safely without widening source permissions."""
from unittest.mock import Mock

import pytest
import requests

from agent.config.settings import settings
from deep_research.access import ResearchAccessError, model_access_scope
from deep_research.model_budget import (
    ResearchTokenBudgetExceeded, completion_budget_scope, post_completion, with_completion_budget,
)
from deep_research.model_client import ResearchModelClient


def response(status=200, **kwargs):
    result = requests.Response()
    result.status_code = status
    result._content = b'{}'
    result.json = lambda: kwargs or {'choices': [], 'usage': {'completion_tokens': 20}}
    return result


def test_reasoning_budget_adds_visible_output_and_does_not_mutate_payload(monkeypatch):
    monkeypatch.setattr(settings, 'RESEARCH_MODEL_REASONING_TOKENS', 3072)
    payload = {'max_tokens': 1200, 'thinking': {'type': 'enabled'},
               'messages': [{'role': 'system', 'content': 'Return json only.'}]}
    sent = with_completion_budget(payload, model='openai/gpt-oss-120b')
    assert sent['max_tokens'] == 4272
    assert '1200 tokens' in sent['messages'][0]['content']
    assert payload['max_tokens'] == 1200
    assert payload['messages'][0]['content'] == 'Return json only.'


def test_non_reasoning_payload_does_not_spend_reasoning_reserve():
    sent = with_completion_budget({'max_tokens': 700, 'enable_thinking': False}, model='qwen-test')
    assert sent['max_tokens'] == 700


def test_shared_attempt_budget_accounts_usage_and_blocks_before_next_io(monkeypatch):
    post = Mock(return_value=response(usage={'completion_tokens': 800}, choices=[]))
    monkeypatch.setattr(requests.Session, 'post', post)
    with completion_budget_scope(1000) as budget:
        post_completion('https://model.test', 'key', {'max_tokens': 900}, 10)
        assert budget.spent == 800
        with completion_budget_scope() as nested:
            assert nested is budget
            with pytest.raises(ResearchTokenBudgetExceeded):
                post_completion('https://model.test', 'key', {'max_tokens': 300}, 10)
    assert post.call_count == 1
    with completion_budget_scope(1000) as fresh:
        assert fresh.spent == 0


def test_429_waits_then_rechecks_current_access_before_retry(monkeypatch):
    limited = response(429)
    limited.headers['Retry-After'] = '2'
    post = Mock(side_effect=[limited, response()])
    sleep = Mock()
    monkeypatch.setattr(requests.Session, 'post', post)
    monkeypatch.setattr('deep_research.model_budget.time.sleep', sleep)
    check = Mock()
    with model_access_scope(check):
        post_completion('https://model.test', 'key', {'max_tokens': 100}, 10)
    sleep.assert_called_once_with(2.25)
    assert post.call_count == 2 and check.call_count == 4


def test_revocation_during_rate_limit_wait_prevents_retry(monkeypatch):
    limited = response(429)
    limited.headers['Retry-After'] = '1'
    post = Mock(return_value=limited)
    allowed = [True]
    def check():
        if not allowed[0]:
            raise ResearchAccessError('research_source_access_revoked')
    monkeypatch.setattr(requests.Session, 'post', post)
    monkeypatch.setattr('deep_research.model_budget.time.sleep', lambda _: allowed.__setitem__(0, False))
    with model_access_scope(check), pytest.raises(ResearchAccessError):
        post_completion('https://model.test', 'key', {'max_tokens': 100}, 10)
    assert post.call_count == 1


def test_excessive_retry_wait_is_not_ignored_or_retried_immediately(monkeypatch):
    limited = response(429)
    limited.headers['Retry-After'] = '120'
    post = Mock(return_value=limited)
    monkeypatch.setattr(requests.Session, 'post', post)
    with pytest.raises(requests.HTTPError):
        post_completion('https://model.test', 'key', {'max_tokens': 100}, 10)
    post.assert_called_once()


def choice(content='', finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}


@pytest.mark.parametrize('failure', ['length', 'oversized'])
def test_truncated_report_stages_and_assembles_in_report_order(monkeypatch, failure):
    client = ResearchModelClient(api_base='unused', api_key='test', model='test')
    replies = iter([choice('', 'length'),
        choice('## Evidence and analysis\n\nCheck local grants and the native read permission before inspecting retrieval. [1]'),
        choice('## Summary\n\nA healthy process does not establish that the user can read sources. [1]'),
        choice('## Limitations and uncertainty\n\nThe source describes a diagnostic procedure; current deployment status requires a live check. [1]')])
    calls = []
    def chat(payload):
        calls.append(payload)
        if failure == 'oversized' and len(calls) == 1:
            next(replies)
            raise requests.HTTPError('Request too large', response=response(413))
        return next(replies)
    monkeypatch.setattr(client, '_chat', chat)
    payload = {'messages': [{'role': 'system', 'content': 'Use only frozen sources.'},
                            {'role': 'user', 'content': 'Question: Diagnose access.\nEvidence: [1] Source.'}]}
    result = client._report_completion(payload, 'en-US')
    body = result['choices'][0]['message']['content']
    assert body.index('## Summary') < body.index('## Evidence and analysis') < body.index('## Limitations')
    assert len(calls) == 4
    assert all(payload['messages'][1] in call['messages'] for call in calls)
    assert not client._structural_issues(body, 1, 'stop', language='en-US')


def test_staged_incomplete_section_is_never_assembled_as_success(monkeypatch):
    client = ResearchModelClient(api_base='unused', api_key='test', model='test')
    replies = iter([choice('', 'length'), choice('## Evidence and analysis\n\nPartial', 'length')])
    monkeypatch.setattr(client, '_chat', lambda _: next(replies))
    with pytest.raises(ValueError, match='research_staged_section_incomplete'):
        client._report_completion({'messages': []}, 'en-US')
