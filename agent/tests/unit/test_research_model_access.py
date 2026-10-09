"""Model transport must recheck the job-local grant, not just workflow edges."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deep_research.access import ResearchAccessError, check_research_model_access, model_access_scope
from deep_research.model_report import EvidenceReportSynthesizer
from deep_research.planner import ModelResearchPlanner


def denied():
    raise ResearchAccessError('research_source_access_revoked')


def test_scope_resets_and_does_not_cross_threads():
    with model_access_scope(denied):
        with pytest.raises(ResearchAccessError):
            check_research_model_access()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(check_research_model_access).result() is None
    assert check_research_model_access() is None


def test_report_blocks_revoked_context_before_model_io(monkeypatch):
    post = Mock()
    monkeypatch.setattr('requests.Session.post', post)
    model = EvidenceReportSynthesizer(api_base='https://model.test/v1', api_key='test-key', model='model')
    with model_access_scope(denied), pytest.raises(ResearchAccessError):
        model._chat({'messages': [{'role': 'user', 'content': 'private source'}]})
    post.assert_not_called()


def test_planner_blocks_revoked_context_before_model_io(monkeypatch):
    send = Mock()
    monkeypatch.setattr('deep_research.planner.urlopen', send)
    model = ModelResearchPlanner(api_base='https://model.test/v1', api_key='test-key', model='model')
    with model_access_scope(denied), pytest.raises(ResearchAccessError):
        model._chat({'messages': []})
    send.assert_not_called()


def test_report_rechecks_after_provider_return_and_between_calls(monkeypatch):
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'choices': []})
    post = Mock(return_value=response)
    monkeypatch.setattr('requests.Session.post', post)
    grant = {'allowed': True}
    calls = []
    def check():
        calls.append(True)
        if not grant['allowed']:
            denied()
    model = EvidenceReportSynthesizer(api_base='https://model.test/v1', api_key='test-key', model='model')
    with model_access_scope(check):
        assert model._chat({'messages': []}) == {'choices': []}
        grant['allowed'] = False
        with pytest.raises(ResearchAccessError):
            model._chat({'messages': []})
    assert len(calls) == 3
    post.assert_called_once()
