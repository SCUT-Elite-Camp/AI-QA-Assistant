from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.research_routes import get_research_control_plane, router
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane


def _client(tmp_path: Path) -> TestClient:
    control_plane = ResearchControlPlane(
        SQLiteResearchRepository(tmp_path / "research.db"),
        source_resolver=InMemoryDocumentResolver(
            {
                "doc-a": {
                    "doc_id": "doc-a",
                    "title": "Local A",
                    "content": "A 的收入为 10。",
                },
                "doc-b": {
                    "doc_id": "doc-b",
                    "title": "Local B",
                    "content": "B 的收入为 20。",
                },
            }
        ),
    )
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = lambda: control_plane
    return TestClient(application)


def test_api_create_view_and_approve_real_control_plane_entities(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/research/jobs",
        headers={"X-User-ID": "alice"},
        json={
            "query": "比较 A 和 B 的收入",
            "source_scope": {"document_ids": ["doc-a", "doc-b"]},
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "awaiting_approval"
    assert job["plan_version"] == 1
    assert job["manifest_hash"]

    plan_response = client.get(f"/api/research/jobs/{job['research_id']}/plan")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["research_id"] == job["research_id"]
    assert plan["manifest_hash"] == job["manifest_hash"]
    assert len(plan["tasks"]) == 3

    wrong = client.post(
        f"/api/research/jobs/{job['research_id']}/approve",
        json={"plan_version": 1, "manifest_hash": "wrong-hash"},
    )
    assert wrong.status_code == 409
    assert wrong.json()["detail"]["code"] == "research_manifest_hash_conflict"

    approved = client.post(
        f"/api/research/jobs/{job['research_id']}/approve",
        headers={"X-User-ID": "alice"},
        json={
            "plan_version": 1,
            "manifest_hash": job["manifest_hash"],
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"


def test_api_cannot_create_job_from_external_source_scope(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/research/jobs",
        json={
            "query": "禁止网络来源",
            "source_scope": {"document_ids": ["https://example.com"]},
        },
    )
    assert response.status_code == 422
