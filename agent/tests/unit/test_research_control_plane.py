from __future__ import annotations

from pathlib import Path

import pytest

from agent.schemas.research import (
    ResearchJobStatus,
    ResearchPlanStatus,
    ResearchPlanRevisionRequest,
    ResearchRequest,
    SourceScope,
)
from deep_research.dispatcher import DurableDispatcher
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane, ResearchControlPlaneError


def _request(*document_ids: str) -> ResearchRequest:
    return ResearchRequest(
        query="比较两份本地资料中的核心指标",
        source_scope=SourceScope(document_ids=list(document_ids)),
    )


def _control_plane(database_path: Path) -> ResearchControlPlane:
    repository = SQLiteResearchRepository(database_path)
    resolver = InMemoryDocumentResolver(
        {
            "doc-a": {"doc_id": "doc-a", "title": "A", "content": "revenue 10"},
            "doc-b": {"doc_id": "doc-b", "title": "B", "content": "revenue 20"},
        }
    )
    return ResearchControlPlane(repository, source_resolver=resolver)


def test_create_persists_real_job_manifest_plan_and_tasks_after_repository_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "research.db"
    control_plane = _control_plane(database_path)

    job = control_plane.create_job(_request("doc-a", "doc-b"), user_id="user-1")
    plan = control_plane.get_plan(job.research_id)
    manifest = control_plane.get_manifest(job.research_id)

    assert job.status == ResearchJobStatus.AWAITING_APPROVAL
    assert job.plan_version == plan.version == 1
    assert job.manifest_hash == manifest.manifest_hash == plan.manifest_hash
    assert [document.doc_id for document in manifest.documents] == ["doc-a", "doc-b"]
    assert len(control_plane.repository.get_tasks(job.research_id, 1)) == 3

    control_plane.repository.close()
    restarted = _control_plane(database_path)
    restored = restarted.get_job(job.research_id)
    assert restored.status == ResearchJobStatus.AWAITING_APPROVAL
    assert restarted.get_manifest(job.research_id).manifest_hash == job.manifest_hash
    assert restarted.get_plan(job.research_id).research_id == job.research_id


def test_approval_binds_exact_plan_version_and_manifest_hash(tmp_path: Path) -> None:
    control_plane = _control_plane(tmp_path / "research.db")
    job = control_plane.create_job(_request("doc-a"))

    with pytest.raises(ResearchControlPlaneError) as wrong_version:
        control_plane.approve_job(
            job.research_id,
            plan_version=2,
            manifest_hash=job.manifest_hash or "",
            approved_by="user-1",
        )
    assert wrong_version.value.code == "research_plan_version_conflict"

    with pytest.raises(ResearchControlPlaneError) as wrong_manifest:
        control_plane.approve_job(
            job.research_id,
            plan_version=1,
            manifest_hash="wrong-manifest-hash",
            approved_by="user-1",
        )
    assert wrong_manifest.value.code == "research_manifest_hash_conflict"

    ready = control_plane.approve_job(
        job.research_id,
        plan_version=1,
        manifest_hash=job.manifest_hash or "",
        approved_by="user-1",
    )
    assert ready.status == ResearchJobStatus.READY
    assert control_plane.get_plan(job.research_id).status == ResearchPlanStatus.APPROVED

    context = control_plane.approved_context(job.research_id)
    assert context.job.research_id == job.research_id
    assert context.plan.version == 1
    assert context.tasks[0].task_id == "task-1"
    assert context.manifest.manifest_hash == context.approval.manifest_hash


def test_dispatcher_claims_only_approved_ready_jobs_once(tmp_path: Path) -> None:
    control_plane = _control_plane(tmp_path / "research.db")
    job = control_plane.create_job(_request("doc-a"))
    control_plane.approve_job(
        job.research_id,
        plan_version=1,
        manifest_hash=job.manifest_hash or "",
        approved_by="user-1",
    )
    received = []
    dispatcher = DurableDispatcher(control_plane, executor=received.append)

    assert dispatcher.scan_once() == [job.research_id]
    assert dispatcher.scan_once() == []
    assert len(received) == 1
    assert received[0].job.status == ResearchJobStatus.RESEARCHING
    assert received[0].plan.research_id == received[0].job.research_id
    assert received[0].manifest.research_id == received[0].job.research_id


def test_dispatcher_does_not_claim_unapproved_jobs(tmp_path: Path) -> None:
    control_plane = _control_plane(tmp_path / "research.db")
    job = control_plane.create_job(_request("doc-a"))
    received = []

    assert DurableDispatcher(control_plane, executor=received.append).scan_once() == []
    assert control_plane.get_job(job.research_id).status == ResearchJobStatus.AWAITING_APPROVAL


def test_plan_revision_supersedes_old_version_and_requires_fresh_approval(
    tmp_path: Path,
) -> None:
    control_plane = _control_plane(tmp_path / "research.db")
    job = control_plane.create_job(_request("doc-a", "doc-b"), user_id="alice")
    control_plane.approve_job(
        job.research_id,
        plan_version=1,
        manifest_hash=job.manifest_hash or "",
        approved_by="alice",
    )
    current = control_plane.get_plan(job.research_id)
    edited_tasks = [task.model_copy(deep=True) for task in current.tasks]
    edited_tasks[0].question = "先核验 A 的收入原文和文档版本"

    revised = control_plane.revise_plan(
        job.research_id,
        ResearchPlanRevisionRequest(
            base_version=1,
            objective="比较 A、B 收入并核验版本",
            tasks=edited_tasks,
            report_spec=current.report_spec,
            revision_note="增加版本核验",
        ),
        revised_by="alice",
    )

    refreshed = control_plane.get_job(job.research_id)
    assert revised.version == refreshed.plan_version == 2
    assert refreshed.status == ResearchJobStatus.AWAITING_APPROVAL
    assert control_plane.get_plan(job.research_id, 1).status == ResearchPlanStatus.SUPERSEDED
    assert control_plane.repository.get_approval(job.research_id, 1).approved_by == "alice"

    with pytest.raises(ResearchControlPlaneError) as old_snapshot:
        control_plane.approve_job(
            job.research_id,
            plan_version=1,
            manifest_hash=job.manifest_hash or "",
            approved_by="alice",
        )
    assert old_snapshot.value.code == "research_plan_version_conflict"

    ready = control_plane.approve_job(
        job.research_id,
        plan_version=2,
        manifest_hash=job.manifest_hash or "",
        approved_by="alice",
    )
    assert ready.status == ResearchJobStatus.READY
    assert control_plane.approved_context(job.research_id).plan.version == 2
