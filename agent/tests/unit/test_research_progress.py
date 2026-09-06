from __future__ import annotations

from pathlib import Path
import json

from agent.schemas.research import (
    ResearchEventType,
    ResearchEventsResponse,
    ResearchJob,
    ResearchJobStatus,
    ResearchProgress,
    ResearchTaskStatus,
    ResearchRequest,
    SourceScope,
)
from deep_research.events import ResearchEventRecorder
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.progress import (
    STAGE_LABELS,
    STAGE_ORDER,
    ResearchProgressService,
)
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane


def _control(tmp_path: Path, research_id: str = "research-progress"):
    repository = SQLiteResearchRepository(tmp_path / "progress.db")
    control = ResearchControlPlane(
        repository,
        source_resolver=InMemoryDocumentResolver(
            {
                "doc-1": {
                    "doc_id": "doc-1",
                    "version": "v1",
                    "content": "部署状态为已完成。",
                }
            }
        ),
        id_factory=lambda: research_id,
    )
    return repository, control


def _request() -> ResearchRequest:
    return ResearchRequest(
        query="核验部署状态",
        source_scope=SourceScope(document_ids=["doc-1"]),
    )


def test_stage_contract_is_frozen() -> None:
    assert STAGE_ORDER == (
        "created",
        "planning",
        "awaiting_approval",
        "ready",
        "execute_tasks",
        "coverage",
        "generate_claims",
        "structural_verification",
        "semantic_verification",
        "render_report",
        "finalize",
        "completed",
    )
    assert tuple(STAGE_LABELS) == STAGE_ORDER
    assert STAGE_LABELS["semantic_verification"] == "正在验证研究结论"


def test_shared_web_fixtures_match_python_contract() -> None:
    fixture_dir = Path(__file__).resolve().parents[2] / "mock" / "research_web_contract"
    for path in fixture_dir.glob("progress_*.json"):
        ResearchProgress.model_validate(json.loads(path.read_text(encoding="utf-8")))
    ResearchEventsResponse.model_validate(
        json.loads((fixture_dir / "events.json").read_text(encoding="utf-8"))
    )


def test_event_repository_is_idempotent_and_cursor_based(tmp_path: Path) -> None:
    repository, control = _control(tmp_path)
    control.enqueue_job(_request())
    recorder = ResearchEventRecorder(repository)

    first = recorder.stage_started("research-progress", "planning")
    replay = recorder.stage_started("research-progress", "planning")
    recorder.stage_completed("research-progress", "planning")

    assert replay.event_id == first.event_id
    events = repository.list_events("research-progress", after_event_id=first.event_id)
    assert [event.event_type for event in events] == [
        ResearchEventType.STAGE_COMPLETED
    ]
    assert len({event.event_key for event in repository.list_events(
        "research-progress", limit=100
    )}) == 4


def test_progress_aggregates_tasks_counts_and_safe_error(tmp_path: Path) -> None:
    repository, control = _control(tmp_path)
    waiting = control.create_job(_request())
    ready = control.approve_job(
        waiting.research_id,
        plan_version=waiting.plan_version or 1,
        manifest_hash=waiting.manifest_hash or "",
        approved_by="alice",
    )
    control.claim_for_execution(ready.research_id)
    task = repository.get_tasks(ready.research_id, ready.plan_version or 1)[0]
    control.events.task_started(ready.research_id, task.task_id)
    control.events.task_finished(
        ready.research_id,
        task.task_id,
        status=ResearchTaskStatus.SUCCEEDED,
        evidence_count=0,
        actions_used=1,
    )

    progress = ResearchProgressService(repository).get_progress(ready.research_id)
    assert ResearchProgress.model_validate(progress.model_dump()) == progress
    assert progress.schema_version == "research.progress.v1"
    assert progress.current_stage == "execute_tasks"
    assert progress.task_total == 3
    assert progress.task_completed == 1
    assert progress.tasks[0].status == ResearchTaskStatus.SUCCEEDED
    assert progress.progress_percent > 20

    current = repository.get_job(ready.research_id)
    repository.update_job(
        ResearchJob.model_validate(
            {
                **current.model_dump(),
                "status": ResearchJobStatus.FAILED,
                "failure_stage": "execute_tasks",
                "error_code": r"C:\\private\\secrets\\token.txt",
            }
        )
    )
    failed = ResearchProgressService(repository).get_progress(ready.research_id)
    assert failed.error is not None
    assert failed.error.code == "research_failed"
    assert "private" not in failed.error.message
    assert "token" not in failed.error.message


def test_cancelled_job_keeps_last_real_stage(tmp_path: Path) -> None:
    repository, control = _control(tmp_path)
    control.enqueue_job(_request())
    control.cancel_job("research-progress")

    progress = ResearchProgressService(repository).get_progress("research-progress")
    assert progress.status == ResearchJobStatus.CANCELLED
    assert progress.current_stage == "created"
    assert progress.progress_percent == 2
    assert progress.error is None
