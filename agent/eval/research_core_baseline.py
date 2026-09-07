"""Run the canonical CP2 policy-conflict baseline and print JSON metrics."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


AGENT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from agent.schemas.research import ResearchRequest, SourceScope  # noqa: E402
from deep_research.evaluation import evaluate_research_run  # noqa: E402
from deep_research.execution import ResearchRuntimeService  # noqa: E402


DOCUMENTS = PROJECT_ROOT / "data-persistence" / "data" / "documents"
DOCUMENT_IDS = [
    "demo-travel-policy-v1",
    "demo-travel-policy-v2",
    "demo-travel-faq-legacy",
]
QUERY = (
    "核验上海酒店650元/晚能否报销，比较正式办法和财务FAQ的500元、700元"
    "住宿限额。员工出差日期为2026年9月10日，已取得直属经理审批。"
)


def main() -> int:
    with TemporaryDirectory(prefix="cp2-research-baseline-") as temporary:
        root = Path(temporary)
        service = ResearchRuntimeService.from_local_catalog(
            database_path=root / "research.db",
            checkpoint_path=root / "checkpoint.db",
            documents_dir=DOCUMENTS,
            id_factory=lambda: "research-policy-baseline",
        )
        try:
            job = service.control_plane.create_job(
                ResearchRequest(
                    query=QUERY,
                    source_scope=SourceScope(document_ids=DOCUMENT_IDS),
                ),
                user_id="baseline-runner",
            )
            service.control_plane.approve_job(
                job.research_id,
                plan_version=job.plan_version or 1,
                manifest_hash=job.manifest_hash or "",
                approved_by="baseline-runner",
            )
            service.scan_once()
            baseline = evaluate_research_run(
                service.control_plane.repository,
                job.research_id,
            )
            print(json.dumps(baseline.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0 if baseline.passed else 1
        finally:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
