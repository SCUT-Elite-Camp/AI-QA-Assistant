"""Research authorization against real SQLite ACLs and actual HTTP credentials."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.research_routes import get_research_control_plane, router
from agent.config.settings import settings
from agent.schemas.research import ResearchCitation, ResearchReport, SourceScope
from agent.service.permission_service import PermissionService
from agent.service.source_access import SourceAccessProvider
from deep_research.access import ResearchAccessPolicy
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane


@pytest.fixture
def environment(tmp_path: Path, monkeypatch):
    acl_path = tmp_path / "web.db"
    with sqlite3.connect(acl_path) as db:
        db.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY, role TEXT, disabled INTEGER);
            CREATE TABLE files(id TEXT PRIMARY KEY, user_id TEXT, doc_id TEXT, visibility TEXT);
            CREATE TABLE file_permissions(file_id TEXT, grant_type TEXT, grant_id TEXT);
            CREATE TABLE user_departments(user_id TEXT, department_id TEXT);
            INSERT INTO users VALUES ('alice','user',0),('bob','user',0),
                ('admin','admin',0),('disabled','admin',1);
            INSERT INTO files VALUES ('public','third','doc-public','shared'),
                ('alice','alice','doc-private','private'),
                ('bob','bob','doc-bob','private'),('grant','third','doc-grant','private');
            INSERT INTO file_permissions VALUES ('grant','department','department-one');
            INSERT INTO user_departments VALUES ('alice','department-one');
        """)
    resolver = InMemoryDocumentResolver({
        doc_id: {"title": title, "space": "kb", "content": "Revenue is 10.", "version": "1"}
        for doc_id, title in {
            "doc-public": "Public document", "doc-private": "Alice document",
            "doc-bob": "Bob secret title", "doc-grant": "Department document",
        }.items()
    })
    control = ResearchControlPlane(
        SQLiteResearchRepository(tmp_path / "research.db"), source_resolver=resolver,
    )
    application = FastAPI()
    application.include_router(router, prefix="/api")
    provider = SourceAccessProvider(mode="approved_snapshot",
        document_loader=lambda doc_id: ({"doc_id": doc_id, **resolver.documents[doc_id]} if doc_id in resolver.documents else None),
        document_ids_loader=lambda: list(resolver.documents))
    application.state.research_access_policy = ResearchAccessPolicy(PermissionService(str(acl_path), source_provider=provider))
    application.dependency_overrides[get_research_control_plane] = lambda: control
    monkeypatch.setattr(settings, "AGENT_API_KEY", "research-security-test-key")
    client = TestClient(application, headers={
        "Authorization": "Bearer research-security-test-key", "X-User-ID": "alice",
    })
    yield client, control, acl_path, application
    client.close()
    control.repository.close()


def _create(client: TestClient, control: ResearchControlPlane) -> dict:
    response = client.post("/api/research/jobs", json={
        "query": "Verify revenue", "source_scope": {"document_ids": ["doc-public"]},
    })
    assert response.status_code == 201, response.text
    job = response.json()
    control.resume_planning_job(job["research_id"])
    return client.get(f"/api/research/jobs/{job['research_id']}").json()


def _calls(research_id: str, manifest_hash: str):
    prefix = f"/api/research/jobs/{research_id}"
    return [
        ("GET", prefix, None), ("GET", prefix + "/plan", None),
        ("GET", prefix + "/report", None), ("GET", prefix + "/progress", None),
        ("GET", prefix + "/events", None), ("GET", prefix + "/evaluation-trace", None),
        ("GET", prefix + "/documents/doc-public/source", None),
        ("POST", prefix + "/approve", {"plan_version": 1, "manifest_hash": manifest_hash}),
        ("POST", prefix + "/cancel", None),
        ("POST", prefix + "/messages", {"message": "批准"}),
        ("POST", prefix + "/plan/revisions", {
            "base_version": 1, "objective": "Verify revenue", "tasks": [],
            "report_spec": {}, "revision_note": "attempt",
        }),
    ]


def test_every_research_route_requires_key_and_trusted_identity(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    calls = _calls(job["research_id"], job["manifest_hash"])
    calls.extend([
        ("GET", "/api/research/documents", None),
        ("POST", "/api/research/jobs", {"query": "Verify", "source_scope": {"document_ids": ["doc-public"]}}),
    ])
    for header, invalid_value in (("Authorization", None), ("Authorization", "Bearer wrong"), ("X-User-ID", None), ("X-User-ID", " ")):
        old = client.headers.get(header)
        if invalid_value is None:
            client.headers.pop(header, None)
        else:
            client.headers[header] = invalid_value
        try:
            for method, url, payload in calls:
                response = client.request(method, url, json=payload)
                assert response.status_code == 401, (method, url, response.text)
        finally:
            client.headers[header] = old


def test_all_job_endpoints_hide_jobs_from_other_users(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    client.headers["X-User-ID"] = "bob"
    for method, url, payload in _calls(job["research_id"], job["manifest_hash"]):
        response = client.request(method, url, json=payload)
        assert response.status_code == 404, (method, url, response.text)


def test_catalog_filters_before_returning_titles_and_scope_rejects_explicit_overreach(environment):
    client, control, _, _ = environment
    catalog = client.get("/api/research/documents")
    assert catalog.status_code == 200
    assert {item["doc_id"] for item in catalog.json()} == {"doc-public", "doc-private", "doc-grant"}
    assert "Bob secret title" not in catalog.text
    response = client.post("/api/research/jobs", json={
        "query": "Read secret", "source_scope": {"document_ids": ["doc-public", "doc-bob"]},
    })
    assert response.status_code == 403
    assert control.repository.list_jobs() == []
    broad = client.post("/api/research/jobs", json={
        "query": "Summarize kb", "source_scope": {"knowledge_base_ids": ["kb"]},
    })
    assert broad.status_code == 201, broad.text
    scope = broad.json()["request"]["source_scope"]
    assert set(scope["document_ids"]) == {"doc-public", "doc-private", "doc-grant"}
    assert scope["knowledge_base_ids"] == []
    assert scope["topic"] == ""


@pytest.mark.parametrize("actor", ["unknown", "disabled"])
def test_unknown_or_disabled_actor_cannot_use_shared_documents(environment, actor):
    client, _, _, _ = environment
    client.headers["X-User-ID"] = actor
    assert client.get("/api/research/documents").status_code == 403
    assert client.post("/api/research/jobs", json={
        "query": "Verify", "source_scope": {"document_ids": ["doc-public"]},
    }).status_code == 403


def test_admin_catalog_is_unrestricted_but_job_ownership_still_applies(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    client.headers["X-User-ID"] = "admin"
    assert len(client.get("/api/research/documents").json()) == 4
    assert client.get(f"/api/research/jobs/{job['research_id']}").status_code == 404


def test_permission_revocation_blocks_saved_job_report_source_events_and_approval(environment):
    client, control, acl_path, _ = environment
    job = _create(client, control)
    control.repository.save_report(ResearchReport(
        report_id="saved-report", research_id=job["research_id"], markdown="# Revenue\n\n10 [1]",
        result_status="complete", citations=[ResearchCitation(
            number=1, evidence_id="e-1", doc_id="doc-public", title="Public document",
            locator="line:1-1", excerpt="Revenue is 10.", content_hash="12345678",
        )], evidence_ids=["e-1"],
    ))
    assert client.get(f"/api/research/jobs/{job['research_id']}/report").status_code == 200
    with sqlite3.connect(acl_path) as db:
        db.execute("UPDATE files SET visibility='private' WHERE doc_id='doc-public'")
    for method, url, payload in _calls(job["research_id"], job["manifest_hash"]):
        response = client.request(method, url, json=payload)
        assert response.status_code == 403, (method, url, response.text)
    assert "doc-public" not in {item["doc_id"] for item in client.get("/api/research/documents").json()}


def test_research_ignores_chat_fail_open_and_does_not_leak_database_errors(environment, monkeypatch):
    client, _, _, application = environment
    monkeypatch.setattr(settings, "PERMISSION_FAIL_OPEN", True)
    policy = application.state.research_access_policy
    monkeypatch.setattr(policy.permission_service, "_connect", lambda: (_ for _ in ()).throw(sqlite3.Error("secret-path.db")))
    response = client.get("/api/research/documents")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "research_permission_unavailable"
    assert "secret-path" not in response.text


def test_source_requires_frozen_manifest_membership_even_if_user_can_access_document(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    assert client.get(f"/api/research/jobs/{job['research_id']}/documents/doc-private/source").status_code == 404


def test_report_cannot_expose_a_document_outside_approved_manifest(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    control.repository.save_report(ResearchReport(
        report_id="untrusted-report", research_id=job["research_id"], markdown="# Secret\n\nSecret [1]",
        result_status="complete", citations=[ResearchCitation(
            number=1, evidence_id="rogue-evidence", doc_id="doc-bob", title="Bob secret title",
            locator="line:1-1", excerpt="Secret", content_hash="12345678",
        )], evidence_ids=["rogue-evidence"],
    ))
    response = client.get(f"/api/research/jobs/{job['research_id']}/report")
    assert response.status_code == 403
    assert "Bob secret" not in response.text


def test_revocation_before_background_planning_does_not_call_planner(environment, monkeypatch):
    client, control, acl_path, application = environment
    control.access_policy = application.state.research_access_policy
    response = client.post("/api/research/jobs", json={
        "query": "Verify", "source_scope": {"document_ids": ["doc-public"]},
    })
    research_id = response.json()["research_id"]
    calls = []
    monkeypatch.setattr(control.planner, "create_plan", lambda *args, **kwargs: calls.append(args))
    with sqlite3.connect(acl_path) as db:
        db.execute("UPDATE files SET visibility='private' WHERE doc_id='doc-public'")
    with pytest.raises(Exception, match="research_source_access_revoked"):
        control.resume_planning_job(research_id)
    assert calls == []
    assert control.get_job(research_id).status.value == "failed"


def test_approved_context_requires_current_permission_not_old_approval(environment):
    client, control, acl_path, application = environment
    control.access_policy = application.state.research_access_policy
    job = _create(client, control)
    control.approve_job(job["research_id"], plan_version=1,
                        manifest_hash=job["manifest_hash"], approved_by="alice")
    with sqlite3.connect(acl_path) as db:
        db.execute("UPDATE files SET visibility='private' WHERE doc_id='doc-public'")
    from deep_research.access import ResearchAccessError
    with pytest.raises(ResearchAccessError, match="access_revoked"):
        control.approved_context(job["research_id"])


def test_source_version_changed_returns_conflict_not_new_content(environment):
    client, control, _, _ = environment
    job = _create(client, control)
    control.source_resolver.documents["doc-public"]["version"] = "2"
    control.source_resolver.documents["doc-public"]["content"] = "Changed private content"
    response = client.get(f"/api/research/jobs/{job['research_id']}/documents/doc-public/source")
    assert response.status_code == 409
    assert "Changed private content" not in response.text


def test_kb_filters_acl_before_manifest_size_limit(environment):
    client, control, _, _ = environment
    # A large inaccessible KB must not prevent selecting a small authorized subset.
    for index in range(110):
        control.source_resolver.documents[f"hidden-{index}"] = {"title": "Hidden", "space": "kb", "content": "private"}
    response = client.post("/api/research/jobs", json={
        "query": "Verify kb", "source_scope": {"knowledge_base_ids": ["kb"]},
    })
    assert response.status_code == 201, response.text
    assert set(response.json()["request"]["source_scope"]["document_ids"]) == {"doc-public", "doc-private", "doc-grant"}
