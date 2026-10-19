"""Explicit local development grants catalog files, while keeping identity and evidence guards."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.config.settings import settings
from agent.schemas.research import ResearchJob, ResearchRequest
from agent.service.permission_service import PermissionService
from deep_research.access import ResearchAccessPolicy, ResearchAccessError
from deep_research.manifest import InMemoryDocumentResolver


@pytest.fixture
def development(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'RESEARCH_DEVELOPMENT_MODE', True)
    monkeypatch.setattr(settings, 'HOST', '127.0.0.1')
    db = tmp_path / 'web.db'
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE users (id TEXT PRIMARY KEY, disabled INTEGER);"
            "INSERT INTO users VALUES ('alice',0),('bob',0),('disabled',1);")
    resolver = InMemoryDocumentResolver({
        'alpha': {'title': 'Alpha access guide', 'version': '1', 'content': 'Current native permission is required.'},
        'beta': {'title': 'Beta private guide', 'version': '2', 'content': 'The saved configuration is a historical snapshot.'},
    })
    provider = SimpleNamespace(list_document_ids=lambda: list(resolver.documents),
        _load=lambda doc_id: resolver.documents.get(doc_id))
    permissions = PermissionService(str(db), source_provider=provider)
    native = Mock(side_effect=AssertionError('Development must not require a file/native grant.'))
    monkeypatch.setattr(permissions, 'get_accessible_doc_ids_strict', native)
    return ResearchAccessPolicy(permissions), resolver, native


@pytest.mark.parametrize('actor', ['alice', 'bob'])
def test_development_resolves_full_catalog_without_file_acl_or_native_request(development, actor):
    policy, resolver, native = development
    request = policy.authorize_request(ResearchRequest(query='Compare the documented procedures.'), actor, resolver)
    assert request.source_scope.document_ids == ['alpha', 'beta']
    assert {d.doc_id for d in policy.list_documents(actor, resolver)} == {'alpha', 'beta'}
    job = ResearchJob(research_id='development-run', user_id=actor, request=request)
    manifest = resolver.resolve(job.research_id, request.source_scope)
    assert policy.authorize_job(job, manifest) == {'alpha', 'beta'}
    native.assert_not_called()


@pytest.mark.parametrize('actor', ['', 'unknown', 'disabled'])
def test_development_still_rejects_missing_unknown_or_disabled_identity(development, actor):
    policy, resolver, _ = development
    with pytest.raises(ResearchAccessError):
        policy.authorize_request(ResearchRequest(query='Inspect access procedures.'), actor, resolver)


def test_development_does_not_allow_version_drift_or_outside_catalog(development):
    policy, resolver, _ = development
    request = policy.authorize_request(ResearchRequest(query='Inspect the approved source.'), 'alice', resolver)
    manifest = resolver.resolve('development-run', request.source_scope)
    job = ResearchJob(research_id='development-run', user_id='alice', request=request)
    resolver.documents['beta']['content'] = 'A different source body.'
    with pytest.raises(ResearchAccessError, match='document_version_changed'):
        policy.authorize_job(job, manifest)
    with pytest.raises(ResearchAccessError, match='source_forbidden'):
        policy.authorize_request(ResearchRequest(query='Read an unavailable file.', source_scope={'document_ids': ['outside']}), 'alice', resolver)


def test_development_flag_cannot_be_enabled_on_a_public_agent_host(monkeypatch):
    monkeypatch.setattr(settings, 'RESEARCH_DEVELOPMENT_MODE', True)
    monkeypatch.setattr(settings, 'HOST', '0.0.0.0')
    with pytest.raises(ValueError, match='requires_loopback_host'):
        ResearchAccessPolicy(SimpleNamespace())


def test_production_policy_keeps_native_authorized_intersection(development, monkeypatch):
    policy, resolver, native = development
    monkeypatch.setattr(settings, 'RESEARCH_DEVELOPMENT_MODE', False)
    native.side_effect = None
    native.return_value = ['alpha']
    production = ResearchAccessPolicy(policy.permission_service)
    assert [d.doc_id for d in production.list_documents('alice', resolver)] == ['alpha']
    native.assert_called_once()
