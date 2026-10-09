from types import SimpleNamespace

import pytest
import requests

from agent.service.source_access import SourceAccessError, SourceAccessProvider


def provider(payload=None, status=200, **kwargs):
    calls = []
    document = {
        "doc_id": "doc-a", "source_url": "https://company.atlassian.net/wiki/spaces/RAG/pages/123/Title",
        "metadata": {"page_id": "123", "source_type": "confluence_cloud"},
    }
    def post(url, **options):
        calls.append((url, options))
        return SimpleNamespace(status_code=status, json=lambda: payload if payload is not None else {"hasPermission": True})
    instance = SourceAccessProvider(
        mode="native", account_bindings={"alice": "account-alice"},
        base_url="https://company.atlassian.net/wiki", email="connector@example.com", token="test-only",
        transport=SimpleNamespace(post=post), document_loader=lambda key: document if key == "doc-a" else None,
        **kwargs,
    )
    return instance, calls, document


def test_current_source_acl_and_no_positive_cache():
    access, calls, _ = provider()
    assert access.filter_allowed("alice", ["doc-a", "doc-a"]) == ["doc-a"]
    assert access.filter_allowed("alice", ["doc-a"]) == ["doc-a"]
    assert len(calls) == 2
    assert calls[0][1]["json"] == {"subject": {"type": "user", "identifier": "account-alice"}, "operation": "read"}
    assert calls[0][1]["allow_redirects"] is False


def test_transient_permission_error_retries_current_request_not_a_cached_grant(monkeypatch):
    access, _, _ = provider()
    responses = iter([503, 200])
    calls = []
    def post(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=next(responses), json=lambda: {"hasPermission": False})
    access.transport = SimpleNamespace(post=post)
    monkeypatch.setattr('agent.service.source_access.time.sleep', lambda _: None)
    assert access.filter_allowed('alice', ['doc-a']) == []
    assert len(calls) == 2


@pytest.mark.parametrize('status', [401, 403, 429])
def test_rejected_permission_checks_are_not_retried(status):
    access, calls, _ = provider(status=status)
    with pytest.raises(SourceAccessError):
        access.filter_allowed('alice', ['doc-a'])
    assert len(calls) == 1


def test_false_permission_is_not_http_success():
    access, _, _ = provider({"hasPermission": False})
    assert access.filter_allowed("alice", ["doc-a"]) == []


def test_missing_mapping_unknown_documents_and_empty_scope_deny():
    access, calls, _ = provider()
    assert access.filter_allowed("bob", ["doc-a"]) == []
    assert access.filter_allowed("alice", ["missing"]) == []
    assert access.filter_allowed("alice", []) == []
    assert calls == []


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_connector_errors_never_fall_back(status):
    access, _, _ = provider(status=status)
    with pytest.raises(SourceAccessError, match="source_permission_check_unavailable"):
        access.filter_allowed("alice", ["doc-a"])


@pytest.mark.parametrize("payload", [{}, {"hasPermission": "true"}, {"hasPermission": 1}])
def test_unknown_permission_is_not_allow(payload):
    access, _, _ = provider(payload)
    with pytest.raises(SourceAccessError, match="source_permission_response_invalid"):
        access.filter_allowed("alice", ["doc-a"])


def test_cross_site_and_quarantine_are_denied():
    access, calls, document = provider()
    document["source_url"] = "https://other.atlassian.net/wiki/spaces/RAG/pages/123/Title"
    assert access.filter_allowed("alice", ["doc-a"]) == []
    document["source_url"] = "https://company.atlassian.net/wiki/spaces/RAG/pages/123/Title"
    document["metadata"]["sync_status"] = "not_visible"
    assert access.filter_allowed("alice", ["doc-a"]) == []
    assert not calls


def test_snapshot_must_be_explicit_and_still_excludes_unavailable_sources():
    access, calls, document = provider()
    access.mode = "approved_snapshot"
    assert access.filter_allowed("bob", ["doc-a"]) == ["doc-a"]
    document["active"] = False
    assert access.filter_allowed("bob", ["doc-a"]) == []
    assert not calls


@pytest.mark.parametrize("url", [
    "http://company.atlassian.net/wiki/spaces/RAG/pages/123/Title",
    "https://company.atlassian.net:8443/wiki/spaces/RAG/pages/123/Title",
    "https://user:password@company.atlassian.net/wiki/spaces/RAG/pages/123/Title",
])
def test_untrusted_origins_never_receive_credentials(url):
    access, calls, document = provider()
    document["source_url"] = url
    assert access.filter_allowed("alice", ["doc-a"]) == []
    assert not calls


def test_explicit_default_https_port_is_same_origin():
    access, calls, document = provider()
    document["source_url"] = "https://company.atlassian.net:443/wiki/spaces/RAG/pages/123/Title"
    assert access.filter_allowed("alice", ["doc-a"]) == ["doc-a"]
    assert len(calls) == 1


def test_transport_timeout_is_not_snapshot_fallback():
    access, _, _ = provider()
    def timeout(*args, **kwargs):
        raise requests.Timeout("test timeout")
    access.transport = SimpleNamespace(post=timeout)
    with pytest.raises(SourceAccessError, match="source_permission_check_unavailable"):
        access.filter_allowed("alice", ["doc-a"])


def test_missing_secret_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_AUTH_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(SourceAccessError, match="source_credentials_unavailable"):
        SourceAccessProvider()


def test_native_is_default_and_invalid_mode_is_not_snapshot(monkeypatch):
    monkeypatch.delenv("SOURCE_ACCESS_MODE", raising=False)
    monkeypatch.delenv("CONFLUENCE_AUTH_ENV_FILE", raising=False)
    assert SourceAccessProvider().mode == "native"
    with pytest.raises(SourceAccessError, match="source_access_mode_invalid"):
        SourceAccessProvider(mode="fail_open")


@pytest.mark.parametrize("value", ['[]', '"alice"', 'not-json'])
def test_invalid_identity_configuration_never_guesses_user(monkeypatch, value):
    monkeypatch.delenv("CONFLUENCE_AUTH_ENV_FILE", raising=False)
    monkeypatch.setenv("CONFLUENCE_ACCOUNT_BINDINGS", value)
    with pytest.raises(SourceAccessError, match="source_identity_configuration_invalid"):
        SourceAccessProvider()
