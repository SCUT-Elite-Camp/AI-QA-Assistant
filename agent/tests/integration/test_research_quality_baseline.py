from __future__ import annotations

from pathlib import Path

from agent.schemas.research import ResearchRequest, ResearchResultStatus, SourceScope
from deep_research.evaluation import evaluate_research_run
from deep_research.execution import ResearchRuntimeService


DOCUMENTS = Path(__file__).resolve().parents[3] / "data-persistence" / "data" / "documents"


def test_policy_demo_meets_structural_quality_baseline(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "baseline.db",
        checkpoint_path=tmp_path / "baseline.graph.db",
        documents_dir=DOCUMENTS,
        id_factory=lambda: "research-quality-baseline",
    )
    try:
        job = service.control_plane.create_job(
            ResearchRequest(
                query=(
                    "核验上海酒店650元/晚能否报销，比较正式办法和FAQ中的"
                    "500元、700元限额，出差日期为2026年9月10日且已有审批。"
                ),
                source_scope=SourceScope(
                    document_ids=[
                        "demo-travel-policy-v1",
                        "demo-travel-policy-v2",
                        "demo-travel-faq-legacy",
                    ]
                ),
            )
        )
        service.control_plane.approve_job(
            job.research_id,
            plan_version=1,
            manifest_hash=job.manifest_hash or "",
            approved_by="baseline",
        )
        service.scan_once()

        baseline = evaluate_research_run(
            service.control_plane.repository,
            job.research_id,
        )
        assert baseline.passed
        assert baseline.result_status == ResearchResultStatus.DEGRADED
        assert baseline.source_scope_violations == 0
        assert baseline.citation_coverage == 1.0
        assert baseline.unsupported_claims_in_report == 0
        assert baseline.conflict_count >= 1
        assert baseline.limitation_count >= 1
        assert baseline.evidence_count == 4
        assert baseline.action_count > 0
    finally:
        service.close()
