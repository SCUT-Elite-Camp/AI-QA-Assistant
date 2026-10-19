from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent.schemas.research import ResearchRequest, SourceScope

from agent.api.research_routes import (
    get_research_access_policy, get_research_actor, get_research_control_plane, router,
)
from deep_research.access import ResearchAccessPolicy
from deep_research.execution import ResearchRuntimeService
from tests.integration.test_research_team import service as team_service, TeamModel




def _application(service: ResearchRuntimeService) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = (
        lambda: service.control_plane
    )
    application.dependency_overrides[get_research_actor] = lambda: "alice"
    application.dependency_overrides[get_research_access_policy] = lambda: ResearchAccessPolicy(
        SimpleNamespace(get_accessible_doc_ids_strict=lambda user_id, **_: None,
            source_provider=SimpleNamespace(_load=lambda doc_id: (
                service.control_plane.source_resolver.documents.get(doc_id)
                if hasattr(service.control_plane.source_resolver, "documents") else service.control_plane.source_resolver._load_catalog().get(doc_id))))
    )
    return application


def test_progress_and_incremental_events_cover_full_http_flow(
    tmp_path: Path, research_documents_dir: Path,
) -> None:
    service, fixture_job = team_service(tmp_path, TeamModel())
    service.control_plane.cancel_job(fixture_job.research_id)

    with TestClient(_application(service)) as client:
        created = client.post(
            "/api/research/jobs",
            headers={"X-User-ID": "alice"},
            json={
                "query": "Explain the documented native access procedures.",
                "source_scope": {
                    "document_ids": ["alpha", "beta"]
                },
            },
        )
        assert created.status_code == 201
        rid = created.json()["research_id"]
        initial = client.get(
            f"/api/research/jobs/{rid}/progress"
        ).json()
        assert initial["status"] == "created"
        assert initial["current_stage"] == "created"
        assert initial["progress_percent"] == 2

        service.scan_once()
        awaiting = client.get(
            f"/api/research/jobs/{rid}/progress"
        ).json()
        assert awaiting["status"] == "awaiting_approval"
        assert awaiting["task_total"] == len(awaiting["tasks"]) == 2
        plan = client.get(
            f"/api/research/jobs/{rid}/plan"
        ).json()
        approved = client.post(
            f"/api/research/jobs/{rid}/approve",
            headers={"X-User-ID": "alice"},
            json={
                "plan_version": plan["version"],
                "manifest_hash": plan["manifest_hash"],
            },
        )
        assert approved.status_code == 200

        first_page = client.get(
            f"/api/research/jobs/{rid}/events?limit=4"
        ).json()
        assert first_page["schema_version"] == "research.events.v1"
        assert len(first_page["events"]) == 4
        cursor = first_page["next_after_event_id"]
        second_page = client.get(
            f"/api/research/jobs/{rid}/events?after_event_id={cursor}&limit=100"
        ).json()
        assert all(event["event_id"] > cursor for event in second_page["events"])

        service.scan_once()
        completed = client.get(
            f"/api/research/jobs/{rid}/progress"
        ).json()
        assert completed["status"] == "completed"
        assert completed["result_status"] == "complete"
        assert completed["current_stage"] == "completed"
        assert completed["progress_percent"] == 100
        assert completed["task_completed"] == completed["task_total"] == 2
        assert completed["evidence_count"] >= 2
        assert completed["finding_count"] >= 1
        assert all(task["status"] == "succeeded" for task in completed["tasks"])
        assert all(stage["status"] == "completed" for stage in completed["stages"])
        assert client.get(
            f"/api/research/jobs/{rid}/report"
        ).status_code == 200

        all_events = client.get(
            f"/api/research/jobs/{rid}/events?limit=100"
        ).json()["events"]
        event_types = {event["event_type"] for event in all_events}
        assert {"task_started", "task_completed", "report_ready", "job_completed"} <= event_types
        assert len({event["event_key"] for event in all_events}) == len(all_events)
    service.close()


def test_progress_api_returns_404_and_validates_event_cursor(tmp_path: Path, research_documents_dir: Path) -> None:
    service, fixture_job = team_service(tmp_path, TeamModel())
    service.control_plane.cancel_job(fixture_job.research_id)
    with TestClient(_application(service)) as client:
        assert client.get(
            "/api/research/jobs/missing/progress"
        ).status_code == 404
        assert client.get(
            "/api/research/jobs/missing/events?after_event_id=-1"
        ).status_code == 404
        assert client.get(
            "/api/research/jobs/missing/events?limit=101"
        ).status_code == 404
        job = service.control_plane.create_job(ResearchRequest(
            query="Compare", source_scope=SourceScope(document_ids=["alpha"])), user_id="alice")
        assert client.get(f"/api/research/jobs/{job.research_id}/events?after_event_id=-1").status_code == 422
        assert client.get(f"/api/research/jobs/{job.research_id}/events?limit=101").status_code == 422
    service.close()
