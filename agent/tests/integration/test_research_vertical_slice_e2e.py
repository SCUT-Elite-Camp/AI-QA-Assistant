from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent.api.research_routes import get_research_control_plane, router
from agent.schemas.research import (
    AcceptanceCriterion,
    ClaimVerificationStatus,
    ResearchBudget,
    ResearchJobStatus,
    ResearchPlan,
    ResearchPlanStatus,
    ResearchPlanValidator,
    ResearchRequest,
    ResearchResultStatus,
    ResearchTask,
    SourceManifest,
    SourceScope,
)
from deep_research.execution import ResearchRuntimeService
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.planner import ResearchPlanner
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane
from deep_research.tools import OriginalRead as AdapterOriginalRead
from deep_research.tools import SearchHit as AdapterSearchHit
from deep_research.verifier import MockSemanticVerifier


FIXTURE_DOCUMENTS = (
    Path(__file__).resolve().parents[2] / "mock" / "research_documents"
)


class SingleCriterionPlanner(ResearchPlanner):
    def __init__(self, *, dimension: str, target: str) -> None:
        self.dimension = dimension
        self.target = target

    def create_plan(
        self,
        request: ResearchRequest,
        manifest: SourceManifest,
        *,
        version: int = 1,
    ) -> ResearchPlan:
        task = ResearchTask(
            task_id="task-1",
            question=request.query,
            purpose="验证固定场景中的核心结论。",
            allowed_tools=["keyword_search", "read_document_range"],
            source_ids=[item.doc_id for item in manifest.documents],
            acceptance_criteria=[
                AcceptanceCriterion(
                    criterion_id="criterion-required",
                    dimension=self.dimension,
                    target=self.target,
                    required=True,
                )
            ],
            max_actions=4,
        )
        plan = ResearchPlan(
            schema_version="research.v2",
            research_id=manifest.research_id,
            version=version,
            objective=request.query,
            source_scope=request.source_scope,
            report_spec=request.report_spec,
            manifest_hash=manifest.manifest_hash,
            tasks=[task],
            budget=ResearchBudget(max_tasks=6, max_actions=8, max_tool_calls=8),
            status=ResearchPlanStatus.AWAITING_APPROVAL,
        )
        return ResearchPlanValidator.validate_or_raise(plan)


class MockLocalAdapter:
    """Mock Search and Mock Read using B's adapter return contracts."""

    def __init__(self, excerpts: dict[str, str]) -> None:
        self.excerpts = excerpts
        self.search_calls = 0
        self.read_calls = 0

    def search(self, query, context, *, source_ids=None, **kwargs):
        self.search_calls += 1
        selected = source_ids or [item.doc_id for item in context.source_manifest.documents]
        return [
            AdapterSearchHit(
                doc_id=doc_id,
                locator_hint="line:1-1",
                snippet=self.excerpts[doc_id],
                score=1.0,
            )
            for doc_id in selected
        ]

    def read_document_range(self, doc_id, context, **kwargs):
        self.read_calls += 1
        manifest_item = next(
            item for item in context.source_manifest.documents if item.doc_id == doc_id
        )
        return AdapterOriginalRead(
            doc_id=doc_id,
            document_version=manifest_item.version,
            locator="line:1-1",
            excerpt=self.excerpts[doc_id],
            content_hash=manifest_item.content_hash,
        )

    def close(self):
        return None


class SimulatedProcessCrash(BaseException):
    pass


class CrashAfterEvidenceLedger:
    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository
        self.crashed = False

    def save_observation(self, item):
        return self.repository.save_observation(item)

    def save_evidence(self, item):
        saved = self.repository.save_evidence(item)
        if not self.crashed:
            self.crashed = True
            raise SimulatedProcessCrash("crash_after_evidence")
        return saved

    def save_finding(self, item):
        return self.repository.save_finding(item)


def _request(query: str, *doc_ids: str) -> ResearchRequest:
    return ResearchRequest(
        query=query,
        source_scope=SourceScope(document_ids=list(doc_ids)),
    )


def _approve(control: ResearchControlPlane, request: ResearchRequest):
    job = control.create_job(request, user_id="alice")
    return control.approve_job(
        job.research_id,
        plan_version=job.plan_version or 1,
        manifest_hash=job.manifest_hash or "",
        approved_by="alice",
    )


def test_manual_api_entry_dispatches_to_traceable_report(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "api-full.db",
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-api-full",
    )
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = (
        lambda: service.control_plane
    )

    with TestClient(application) as client:
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
        assert created.json()["status"] == "created"

        assert service.scan_once() == ["research-api-full"]
        job = client.get("/api/research/jobs/research-api-full").json()
        assert job["status"] == "awaiting_approval"
        plan = client.get("/api/research/jobs/research-api-full/plan").json()

        approved = client.post(
            "/api/research/jobs/research-api-full/approve",
            headers={"X-User-ID": "alice"},
            json={
                "plan_version": plan["version"],
                "manifest_hash": plan["manifest_hash"],
            },
        )
        assert approved.json()["status"] == "ready"

        assert service.scan_once() == ["research-api-full"]
        completed = client.get("/api/research/jobs/research-api-full").json()
        report = client.get("/api/research/jobs/research-api-full/report")
        assert completed["status"] == "completed"
        assert completed["result_status"] == "complete"
        assert report.status_code == 200
        assert "project-alpha / line:" in report.json()["markdown"]
        assert "project-beta / line:" in report.json()["markdown"]
    service.close()


def test_cancelled_job_is_terminal_and_not_dispatched(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "cancel.db",
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-cancelled",
    )
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = (
        lambda: service.control_plane
    )

    with TestClient(application) as client:
        created = client.post(
            "/api/research/jobs",
            headers={"X-User-ID": "alice"},
            json={
                "query": "取消这次本地研究",
                "source_scope": {"document_ids": ["project-alpha"]},
            },
        )
        assert created.status_code == 201

        cancelled = client.post(
            "/api/research/jobs/research-cancelled/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert service.scan_once() == []

        current = client.get(
            "/api/research/jobs/research-cancelled"
        ).json()
        assert current["status"] == "cancelled"
        assert client.get(
            "/api/research/jobs/research-cancelled/report"
        ).status_code == 404
    service.close()


def test_mock_full_vertical_slice_reaches_complete_report(tmp_path: Path) -> None:
    documents = {
        "mock-doc": {
            "doc_id": "mock-doc",
            "version": "v1",
            "content": "部署状态为已完成，验收记录已归档。",
        }
    }
    repository = SQLiteResearchRepository(tmp_path / "mock.db")
    control = ResearchControlPlane(
        repository,
        source_resolver=InMemoryDocumentResolver(documents),
        id_factory=lambda: "research-mock-full",
    )
    adapter = MockLocalAdapter(
        {"mock-doc": "部署状态为已完成，验收记录已归档。"}
    )
    service = ResearchRuntimeService(
        control,
        adapter,  # type: ignore[arg-type]
        InMemorySaver(),
        semantic_verifier=MockSemanticVerifier({}),
    )

    _approve(control, _request("核验部署完成情况", "mock-doc"))
    assert service.scan_once() == ["research-mock-full"]

    job = repository.get_job("research-mock-full")
    report = repository.get_report("research-mock-full")
    assert job.status == ResearchJobStatus.COMPLETED
    assert job.result_status == ResearchResultStatus.COMPLETE
    assert job.task_completed == job.task_total == 3
    assert adapter.search_calls == adapter.read_calls == 3
    assert len(repository.list_observations(job.research_id)) == 3
    assert len(repository.list_evidence(job.research_id)) == 3
    assert "[E:evidence-" in report.markdown
    assert "## 证据索引" in report.markdown
    service.close()


def test_fixed_local_fixture_e2e_is_repeatable_and_traceable(tmp_path: Path) -> None:
    reports: list[str] = []
    for run in (1, 2):
        service = ResearchRuntimeService.from_local_catalog(
            database_path=tmp_path / f"fixed-{run}.db",
            checkpoint_path=tmp_path / f"fixed-{run}.graph.db",
            documents_dir=FIXTURE_DOCUMENTS,
            id_factory=lambda: "research-fixed-local",
        )
        control = service.control_plane
        _approve(
            control,
            _request(
                "比较 Alpha 与 Beta 的部署状态",
                "project-alpha",
                "project-beta",
            ),
        )
        assert service.scan_once() == ["research-fixed-local"]
        job = control.get_job("research-fixed-local")
        report = control.repository.get_report(job.research_id)
        evidence = control.repository.list_evidence(job.research_id)
        assert job.status == ResearchJobStatus.COMPLETED
        assert job.result_status == ResearchResultStatus.COMPLETE
        assert {item.doc_id for item in evidence} == {
            "project-alpha",
            "project-beta",
        }
        assert all(item.locator.startswith("line:") for item in evidence)
        assert "project-alpha / line:" in report.markdown
        assert "project-beta / line:" in report.markdown
        reports.append(report.markdown)
        service.close()

    assert reports[0] == reports[1]


def test_insufficient_material_completes_as_degraded(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "insufficient.db",
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-insufficient",
        planner=SingleCriterionPlanner(dimension="metric", target="利润"),
    )
    control = service.control_plane
    _approve(
        control,
        _request("资料中的利润是多少", "incomplete-metrics"),
    )
    service.scan_once()

    job = control.get_job("research-insufficient")
    coverage = control.repository.get_coverage(job.research_id)
    report = control.repository.get_report(job.research_id)
    assert job.status == ResearchJobStatus.COMPLETED
    assert job.result_status == ResearchResultStatus.DEGRADED
    assert coverage.missing == ["criterion-required"]
    assert "缺失必需验收条件：criterion-required" in report.markdown
    service.close()


def test_conflicting_evidence_is_disclosed_not_selected(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "conflict.db",
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-conflict",
        planner=SingleCriterionPlanner(dimension="evidence", target="预算"),
    )
    control = service.control_plane
    _approve(
        control,
        _request("核验 2026 年度预算", "budget-a", "budget-b"),
    )
    service.scan_once()

    job = control.get_job("research-conflict")
    semantic = control.repository.list_verifications(job.research_id)[-1]
    report = control.repository.get_report(job.research_id)
    assert job.result_status == ResearchResultStatus.DEGRADED
    assert semantic.status == ClaimVerificationStatus.CONFLICTING
    assert "证据存在冲突，无法形成确定结论" in report.markdown
    assert "100 万元" in report.markdown
    assert "确定结论：2026 年度预算为 100 万元" not in report.markdown
    service.close()


def test_restart_recovers_created_job_and_reuses_frozen_manifest(tmp_path: Path) -> None:
    database = tmp_path / "planning.db"
    service = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-planning-restart",
    )
    created = service.control_plane.enqueue_job(
        _request("核验 Alpha 部署状态", "project-alpha"),
        user_id="alice",
    )
    assert created.status == ResearchJobStatus.CREATED
    service.close()

    restarted = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
    )
    assert restarted.scan_once() == ["research-planning-restart"]
    recovered = restarted.control_plane.get_job("research-planning-restart")
    assert recovered.status == ResearchJobStatus.AWAITING_APPROVAL
    assert restarted.control_plane.get_manifest(recovered.research_id).manifest_hash
    restarted.close()


def test_restart_after_manifest_checkpoint_reuses_same_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "manifest-restart.db"
    first = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-manifest-restart",
    )
    request = _request("核验 Alpha 部署状态", "project-alpha")
    created = first.control_plane.enqueue_job(request, user_id="alice")
    first.control_plane.repository.transition_job(
        created.research_id,
        expected_statuses=[ResearchJobStatus.CREATED],
        status=ResearchJobStatus.PLANNING,
        current_stage="planning",
    )
    manifest = first.control_plane.source_resolver.resolve(
        created.research_id,
        request.source_scope,
    )
    first.control_plane.repository.save_manifest(manifest)
    first.control_plane.repository.transition_job(
        created.research_id,
        expected_statuses=[ResearchJobStatus.PLANNING],
        status=ResearchJobStatus.PLANNING,
        current_stage="planning",
        manifest_hash=manifest.manifest_hash,
    )
    first.close()

    restarted = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
    )
    assert restarted.scan_once() == ["research-manifest-restart"]
    recovered = restarted.control_plane.get_manifest("research-manifest-restart")
    assert recovered.manifest_hash == manifest.manifest_hash
    assert restarted.control_plane.get_job(
        "research-manifest-restart"
    ).status == ResearchJobStatus.AWAITING_APPROVAL
    restarted.close()


def test_restart_without_safe_checkpoint_fails_explicitly(tmp_path: Path) -> None:
    database = tmp_path / "unsafe-restart.db"
    first = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-unsafe-restart",
    )
    _approve(
        first.control_plane,
        _request("核验 Alpha 部署状态", "project-alpha"),
    )
    first.control_plane.claim_for_execution("research-unsafe-restart")
    first.close()

    restarted = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        documents_dir=FIXTURE_DOCUMENTS,
    )
    assert restarted.scan_once() == []
    failed = restarted.control_plane.get_job("research-unsafe-restart")
    assert failed.status == ResearchJobStatus.FAILED
    assert failed.error_code == "research_checkpoint_missing"
    restarted.close()


def test_restart_after_evidence_does_not_duplicate_evidence(tmp_path: Path) -> None:
    database = tmp_path / "evidence-restart.db"
    checkpoint = tmp_path / "evidence-restart.graph.db"
    first = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        checkpoint_path=checkpoint,
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-evidence-restart",
    )
    _approve(
        first.control_plane,
        _request("核验 Alpha 部署状态", "project-alpha"),
    )
    first.pipeline.ledger = CrashAfterEvidenceLedger(
        first.control_plane.repository
    )
    with pytest.raises(SimulatedProcessCrash, match="crash_after_evidence"):
        first.scan_once()
    persisted_ids = {
        item.evidence_id
        for item in first.control_plane.repository.list_evidence(
            "research-evidence-restart"
        )
    }
    assert len(persisted_ids) == 1
    assert first.control_plane.get_job(
        "research-evidence-restart"
    ).status == ResearchJobStatus.RESEARCHING
    first.close()

    restarted = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        checkpoint_path=checkpoint,
        documents_dir=FIXTURE_DOCUMENTS,
    )
    assert restarted.scan_once() == ["research-evidence-restart"]
    evidence = restarted.control_plane.repository.list_evidence(
        "research-evidence-restart"
    )
    assert persisted_ids.issubset({item.evidence_id for item in evidence})
    assert len(evidence) == len({item.evidence_id for item in evidence}) == 3
    assert restarted.control_plane.get_job(
        "research-evidence-restart"
    ).status == ResearchJobStatus.COMPLETED
    restarted.close()


def test_restart_after_report_persistence_finishes_finalize(tmp_path: Path) -> None:
    database = tmp_path / "report-restart.db"
    checkpoint = tmp_path / "report-restart.graph.db"
    crashed = False

    def crash_before_finalize(research_id: str, event: str) -> None:
        nonlocal crashed
        if event == "report_persisted" and not crashed:
            crashed = True
            raise SimulatedProcessCrash("crash_before_finalize")

    first = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        checkpoint_path=checkpoint,
        documents_dir=FIXTURE_DOCUMENTS,
        id_factory=lambda: "research-report-restart",
        stage_hook=crash_before_finalize,
    )
    _approve(
        first.control_plane,
        _request("核验 Alpha 部署状态", "project-alpha"),
    )
    with pytest.raises(SimulatedProcessCrash, match="crash_before_finalize"):
        first.scan_once()
    assert first.control_plane.repository.get_report("research-report-restart")
    assert first.control_plane.get_job(
        "research-report-restart"
    ).status == ResearchJobStatus.SYNTHESIZING
    first.close()

    restarted = ResearchRuntimeService.from_local_catalog(
        database_path=database,
        checkpoint_path=checkpoint,
        documents_dir=FIXTURE_DOCUMENTS,
    )
    assert restarted.scan_once() == ["research-report-restart"]
    assert restarted.control_plane.get_job(
        "research-report-restart"
    ).status == ResearchJobStatus.COMPLETED
    assert len(
        [
            item
            for item in restarted.control_plane.repository._list_entities(
                "report", "research-report-restart"
            )
        ]
    ) == 1
    restarted.close()
