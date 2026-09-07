from __future__ import annotations

from pathlib import Path

from agent.schemas.research import ResearchJobStatus, ResearchRequest, ResearchResultStatus, SourceScope
from deep_research.execution import ResearchRuntimeService


DEMO_DOCUMENTS = (
    Path(__file__).resolve().parents[3]
    / "data-persistence"
    / "data"
    / "documents"
)
DEMO_IDS = [
    "demo-travel-policy-v1",
    "demo-travel-policy-v2",
    "demo-travel-faq-legacy",
]
DEMO_QUERY = (
    "核验上海酒店 650 元/晚能否报销，比较正式办法和财务 FAQ 的 500 元、700 元"
    "住宿限额。员工出差日期为 2026 年 9 月 10 日，已取得直属经理审批。"
)


def test_policy_conflict_demo_exercises_the_cp2_core_chain(tmp_path: Path) -> None:
    service = ResearchRuntimeService.from_local_catalog(
        database_path=tmp_path / "research-demo.db",
        documents_dir=DEMO_DOCUMENTS,
        id_factory=lambda: "research-policy-demo",
    )
    try:
        job = service.control_plane.enqueue_job(
            ResearchRequest(
                query=DEMO_QUERY,
                source_scope=SourceScope(document_ids=DEMO_IDS),
            ),
            user_id="demo-user",
        )
        assert job.status == ResearchJobStatus.CREATED

        assert service.scan_once() == ["research-policy-demo"]
        planned = service.control_plane.get_job(job.research_id)
        plan = service.control_plane.get_plan(job.research_id)
        manifest = service.control_plane.get_manifest(job.research_id)
        assert planned.status == ResearchJobStatus.AWAITING_APPROVAL
        assert plan.manifest_hash == manifest.manifest_hash == planned.manifest_hash
        assert [task.max_actions for task in plan.tasks] == [2, 4, 2]
        assert "FAQ页面" in plan.tasks[1].question

        service.control_plane.approve_job(
            job.research_id,
            plan_version=plan.version,
            manifest_hash=manifest.manifest_hash,
            approved_by="demo-user",
        )
        assert service.scan_once() == ["research-policy-demo"]

        completed = service.control_plane.get_job(job.research_id)
        report = service.control_plane.repository.get_report(job.research_id)
        events = service.control_plane.repository.list_events(job.research_id)
        assert completed.status == ResearchJobStatus.COMPLETED
        assert completed.result_status == ResearchResultStatus.DEGRADED
        assert completed.evidence_count == 4
        assert "## 资料冲突" in report.markdown
        assert "## 仍需确认" in report.markdown
        assert "## 来源" in report.markdown
        assert "星云科技差旅管理办法（现行版）" in report.markdown
        assert "财务报销 FAQ（待同步页面）" in report.markdown
        assert "700元" in report.markdown
        assert "500元" in report.markdown
        assert "发票合规性" in report.markdown
        assert "criterion-" not in report.markdown
        assert "claim-finding-" not in report.markdown
        assert "evidence-" not in report.markdown
        assert {citation.doc_id for citation in report.citations} == {
            "demo-travel-policy-v2",
            "demo-travel-faq-legacy",
        }
        assert all(citation.title for citation in report.citations)
        assert report.conflicts[0].conflict_type == "version"
        assert report.conflicts[0].resolution_status == "resolved_by_authority"
        assert report.limitations[0].code == "source_boundary"
        assert len(events) >= 30
    finally:
        service.close()
