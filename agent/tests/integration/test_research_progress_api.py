from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.research_routes import get_research_control_plane, router
from deep_research.execution import ResearchRuntimeService


FIXTURE_DOCUMENTS = (
    Path(__file__).resolve().parents[2] / "mock" / "research_documents"
)


def _application(service: ResearchRuntimeService) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = (
        lambda: service.control_plane
    )
    return application


def test_progress_and_incremental_events_cover_full_http_flow(
    tmp_path: Path,
) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "progress-api.db",
        checkpoint_path=tmp_path / "progress-api.graph.db",
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-progress-api",
    )

    with TestClient(_application(service)) as client:
        created = client.post(
            "/api/research/jobs",
            headers={"X-User-ID": "alice"},
            json={
                "query": "比较 Alpha 与 Beta 的部署状态",
                "source_scope": {
                    "document_ids": ["project-alpha", "project-beta"]
                },
            },
        )
        assert created.status_code == 201
        initial = client.get(
            "/api/research/jobs/research-progress-api/progress"
        ).json()
        assert initial["status"] == "created"
        assert initial["current_stage"] == "created"
        assert initial["progress_percent"] == 2

        service.scan_once()
        awaiting = client.get(
            "/api/research/jobs/research-progress-api/progress"
        ).json()
        assert awaiting["status"] == "awaiting_approval"
        assert awaiting["task_total"] == len(awaiting["tasks"]) == 3
        plan = client.get(
            "/api/research/jobs/research-progress-api/plan"
        ).json()
        approved = client.post(
            "/api/research/jobs/research-progress-api/approve",
            headers={"X-User-ID": "alice"},
            json={
                "plan_version": plan["version"],
                "manifest_hash": plan["manifest_hash"],
            },
        )
        assert approved.status_code == 200

        first_page = client.get(
            "/api/research/jobs/research-progress-api/events?limit=4"
        ).json()
        assert first_page["schema_version"] == "research.events.v1"
        assert len(first_page["events"]) == 4
        cursor = first_page["next_after_event_id"]
        second_page = client.get(
            f"/api/research/jobs/research-progress-api/events?after_event_id={cursor}&limit=100"
        ).json()
        assert all(event["event_id"] > cursor for event in second_page["events"])

        service.scan_once()
        completed = client.get(
            "/api/research/jobs/research-progress-api/progress"
        ).json()
        assert completed["status"] == "completed"
        assert completed["result_status"] == "complete"
        assert completed["current_stage"] == "completed"
        assert completed["progress_percent"] == 100
        assert completed["task_completed"] == completed["task_total"] == 3
        assert completed["evidence_count"] >= 2
        assert completed["claim_count"] >= 1
        assert all(task["status"] == "succeeded" for task in completed["tasks"])
        assert all(stage["status"] == "completed" for stage in completed["stages"])
        assert client.get(
            "/api/research/jobs/research-progress-api/report"
        ).status_code == 200

        all_events = client.get(
            "/api/research/jobs/research-progress-api/events?limit=100"
        ).json()["events"]
        event_types = {event["event_type"] for event in all_events}
        assert {"task_started", "task_completed", "report_ready", "job_completed"} <= event_types
        assert len({event["event_key"] for event in all_events}) == len(all_events)
    service.close()


def test_progress_api_returns_404_and_validates_event_cursor(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "progress-errors.db",
        documents_dir=FIXTURE_DOCUMENTS,
    )
    with TestClient(_application(service)) as client:
        assert client.get(
            "/api/research/jobs/missing/progress"
        ).status_code == 404
        assert client.get(
            "/api/research/jobs/missing/events?after_event_id=-1"
        ).status_code == 422
        assert client.get(
            "/api/research/jobs/missing/events?limit=101"
        ).status_code == 422
    service.close()
