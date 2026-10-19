"""Completion exhaustion must stage safely without widening source permissions."""
from unittest.mock import Mock

import pytest
import requests

from agent.config.settings import settings
from deep_research.access import ResearchAccessError, model_access_scope
from deep_research.model_budget import (
    ResearchTokenBudgetExceeded, completion_budget_scope, post_completion, with_completion_budget,
    completion_headroom_scope, completion_budget_status,
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


@pytest.mark.parametrize('enabled', [False, True])
def test_deepseek_uses_native_thinking_switch_and_matching_completion_cap(monkeypatch, enabled):
    monkeypatch.setattr(settings, 'RESEARCH_MODEL_REASONING_TOKENS', 512)
    client = ResearchModelClient(api_base='https://model.test/v1', api_key='test', model='deepseek-test')
    sent = []
    monkeypatch.setattr('deep_research.model_client.post_completion', lambda base, key, payload, timeout:
        sent.append(payload) or {'choices': []})
    client._chat({'model': 'deepseek-test', 'max_tokens': 700, 'enable_thinking': enabled,
                  'messages': [{'role': 'user', 'content': 'Return a short supported summary.'}]})
    assert sent[0]['thinking'] == {'type': 'enabled' if enabled else 'disabled'}
    assert 'enable_thinking' not in sent[0]
    assert sent[0]['max_tokens'] == 700 + (512 if enabled else 0)


def test_reviewer_has_separate_reasoning_allowance_without_sending_internal_options(monkeypatch):
    monkeypatch.setattr(settings, 'RESEARCH_MODEL_REASONING_TOKENS', 512)
    monkeypatch.setattr(settings, 'RESEARCH_REVIEW_REASONING_TOKENS', 8192)
    client = ResearchModelClient(api_base='https://model.test/v1', api_key='test', model='deepseek-test')
    sent = []
    monkeypatch.setattr('deep_research.model_client.post_completion', lambda base, key, payload, timeout:
        sent.append(payload) or {'choices': []})
    client._chat({'model': 'deepseek-test', 'max_tokens': 700, 'enable_thinking': True,
        '_research_reasoning_tokens': 2048, 'messages': [{'role': 'user', 'content': 'Review supported facts.'}]})
    assert sent[0]['max_tokens'] == 2748 and '_research_reasoning_tokens' not in sent[0]


def test_research_timeout_is_configured_for_long_reasoning_but_explicit_override_is_preserved(monkeypatch):
    from deep_research.planner import ModelResearchPlanner
    monkeypatch.setattr(settings, 'RESEARCH_MODEL_TIMEOUT_SECONDS', 180)
    assert ResearchModelClient(api_base='unused', api_key='test', model='test').timeout_seconds == 180
    assert ResearchModelClient(api_base='unused', api_key='test', model='test', timeout_seconds=30).timeout_seconds == 30
    assert ModelResearchPlanner(api_base='unused', api_key='test', model='test').timeout_seconds == 180
    assert ModelResearchPlanner(api_base='unused', api_key='test', model='test', timeout_seconds=30).timeout_seconds == 30


@pytest.mark.parametrize('enabled', [False, True])
def test_control_thinking_option_preserves_explorer_and_global_defaults(monkeypatch, enabled):
    from deep_research.team import ResearchRoleModel
    monkeypatch.setattr(settings, 'RESEARCH_CONTROL_THINKING', enabled)
    model = ResearchRoleModel(api_base='https://model.test', api_key='test', model='deepseek-test')
    sent = []
    monkeypatch.setattr(model.client, '_chat', lambda p:
        sent.append(p) or choice('{}'))
    for role in ['explorer', 'repair', 'reviewer', 'coordinator']:
        model.json(role, 'Return a short decision.', {})
    assert all('enable_thinking' not in p for p in sent[:2])
    assert all(('enable_thinking' not in p) if enabled else p['enable_thinking'] is False for p in sent[2:])


@pytest.mark.parametrize('content', [
    '{"type":"json_object","content":{"findings":[],"missing":["No verified evidence."]}}',
    '{"type":"json_object","findings":[],"missing":["No verified evidence."]}',
    '{"action":"finish","findings":[],"missing":["No verified evidence."]}',
])
def test_provider_format_envelope_normalizes_without_inventing_evidence(monkeypatch, content):
    from deep_research.team import ResearchRoleModel
    model = ResearchRoleModel(api_base='https://model.test', api_key='test', model='deepseek-test')
    monkeypatch.setattr(model.client, '_chat', lambda p: choice(content))
    result = model.json('explorer', 'Finish from originals.', {})
    assert result == {'action': 'finish', 'findings': [], 'missing': ['No verified evidence.']}


def test_truncated_reviewer_stages_verdict_with_reasoning_and_original_inputs_preserved(monkeypatch):
    from deep_research.team import ResearchRoleModel
    monkeypatch.setattr(settings, 'RESEARCH_CONTROL_THINKING', True)
    model = ResearchRoleModel(api_base='https://model.test', api_key='test', model='deepseek-test')
    sent = []
    def chat(payload):
        sent.append(payload)
        if len(sent) == 1:
            return {'choices': [{'finish_reason': 'length', 'message': {'content': '',
                'reasoning_content': 'Draft observation: check citation support against the original.'}}]}
        return choice('{"status":"passed","checked_citation_numbers":[1],"checked_block_ids":[0],"issues":[]}')
    monkeypatch.setattr(model.client, '_chat', chat)
    result = model.json('reviewer', 'Audit the report against originals.', {'fresh_originals': ['original'], 'report_markdown': 'Report [1]'})
    assert result['status'] == 'passed' and len(sent) == 2
    assert sent[1]['messages'][:-1] == sent[0]['messages']
    assert 'untrusted draft analysis' in sent[1]['messages'][-1]['content']
    assert all('enable_thinking' not in p for p in sent)


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


def test_parallel_explorers_cannot_spend_downstream_headroom(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Barrier
    barrier = Barrier(2)
    def reserve():
        barrier.wait(timeout=5)
        try:
            budget.reserve(400)
            return True
        except ResearchTokenBudgetExceeded:
            return False
    with completion_budget_scope(1000) as budget, completion_headroom_scope(500):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, reserve) for _ in range(2)]
            assert sum(f.result() for f in futures) == 1
        assert completion_budget_status()['remaining'] == 600
    assert completion_budget_status() is None


def test_downstream_role_can_use_reserved_tokens_but_explorer_cannot(monkeypatch):
    post = Mock(return_value=response(usage={'completion_tokens': 50}, choices=[]))
    monkeypatch.setattr(requests.Session, 'post', post)
    with completion_budget_scope(1000):
        with completion_headroom_scope(600), pytest.raises(ResearchTokenBudgetExceeded):
            post_completion('https://model.test', 'key', {'max_tokens': 500}, 10)
        post.assert_not_called()
        post_completion('https://model.test', 'key', {'max_tokens': 500}, 10)
        post.assert_called_once()


def test_final_verdict_uses_remaining_tokens_instead_of_rejecting_its_larger_normal_cap(monkeypatch):
    post = Mock(return_value=response(usage={'completion_tokens': 100}, choices=[]))
    monkeypatch.setattr(requests.Session, 'post', post)
    payload = {'max_tokens': 700, '_research_finalize': True, 'messages': [{'role': 'user', 'content': 'Return verdict.'}]}
    with completion_budget_scope(1000, spent=750) as budget:
        post_completion('https://model.test', 'key', payload, 10)
        assert budget.spent == 850
    sent = post.call_args.kwargs['json']
    assert sent['max_tokens'] == 250 and '_research_finalize' not in sent
    assert '250 completion tokens' in sent['messages'][-1]['content']
    assert payload['max_tokens'] == 700 and len(payload['messages']) == 1


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
