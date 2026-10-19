"""Model transport must recheck the job-local grant, not just workflow edges."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deep_research.access import ResearchAccessError, check_research_model_access, model_access_scope
from deep_research.model_client import ResearchModelClient
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
    model = ResearchModelClient(api_base='https://model.test/v1', api_key='test-key', model='model')
    with model_access_scope(denied), pytest.raises(ResearchAccessError):
        model._chat({'messages': [{'role': 'user', 'content': 'private source'}]})
    post.assert_not_called()


def test_planner_blocks_revoked_context_before_model_io(monkeypatch):
    send = Mock()
    monkeypatch.setattr('requests.Session.post', send)
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
    model = ResearchModelClient(api_base='https://model.test/v1', api_key='test-key', model='model')
    with model_access_scope(check):
        assert model._chat({'messages': []}) == {'choices': []}
        grant['allowed'] = False
        with pytest.raises(ResearchAccessError):
            model._chat({'messages': []})
    assert len(calls) == 3
    post.assert_called_once()


def test_missing_planner_model_cannot_produce_a_fallback_plan(monkeypatch):
    from deep_research.planner import PlannerError
    from deep_research.manifest import InMemoryDocumentResolver
    from agent.schemas.research import ResearchRequest, SourceScope
    request = ResearchRequest(query='Inspect the access procedure.', source_scope=SourceScope(document_ids=['alpha']))
    manifest = InMemoryDocumentResolver({'alpha': {'title': 'Alpha guide', 'content': 'Original access procedure.'}}).resolve('research-plan', request.source_scope)
    post = Mock()
    monkeypatch.setattr('requests.Session.post', post)
    model = ModelResearchPlanner(api_base='https://model.test/v1', api_key='', model='thinking')
    with pytest.raises(PlannerError, match='model_required'):
        model.create_plan(request, manifest)
    post.assert_not_called()


def test_model_cannot_add_unlisted_files_to_the_human_approval_plan(monkeypatch):
    import json
    from deep_research.planner import PlannerError
    from deep_research.manifest import InMemoryDocumentResolver
    from agent.schemas.research import ResearchRequest, SourceScope
    request = ResearchRequest(query='Inspect source access.', source_scope=SourceScope(document_ids=['alpha']))
    manifest = InMemoryDocumentResolver({'alpha': {'title': 'Alpha guide', 'content': 'Documented access procedure.'}}).resolve('research-plan', request.source_scope)
    model = ModelResearchPlanner(api_base='unused', api_key='test', model='thinking')
    specs = [{'task_id': f'task-{i}', 'question': 'Inspect access.', 'purpose': 'Verify the original.',
        'source_numbers': [999], 'criteria': ['Verify permission requirements.']} for i in (1, 2)]
    monkeypatch.setattr(model, '_chat', lambda _: {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'tasks': specs})}}]})
    with pytest.raises(PlannerError, match='outside_catalogue'):
        model._team_tasks(request, manifest)
