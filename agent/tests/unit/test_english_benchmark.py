from __future__ import annotations

import json
from pathlib import Path
import re

from agent.schemas.research import CoverageResult, ReportSpec, ResearchRequest, SourceScope
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane
from deep_research.renderer import MarkdownReportRenderer


def test_english_round_preserves_source_scope_and_uses_english_rubrics():
    root = Path(__file__).resolve().parents[3]
    datasets = root / "eval/deep_research_a/datasets"
    original = json.loads((datasets / "cases.v1.json").read_text(encoding="utf-8"))
    english = json.loads((datasets / "cases.en.v1.json").read_text(encoding="utf-8"))
    assert english["language"] == "en-US"
    assert len(english["cases"]) == 18
    assert not re.search(r"[\u4e00-\u9fff]", json.dumps(english, ensure_ascii=False))
    for old, new in zip(original["cases"], english["cases"]):
        for key in ("case_id", "allowed_document_ids", "forbidden_document_ids", "key_source_locations", "expected_behavior"):
            assert new[key] == old[key]
        assert new["report_language"] == "en-US"


def test_english_report_fallback_keeps_language_when_evidence_is_missing():
    assert ReportSpec().language == "en-US"
    report = MarkdownReportRenderer().render(
        research_id="english-empty", objective="What is the production SLA?", claims=[], evidence=[],
        coverage=CoverageResult(research_id="english-empty", covered=[], missing=["sla"], sufficient=False),
        language="en-US",
    )
    assert "insufficient" in report.markdown
    assert "## Sources" in report.markdown
    assert not re.search(r"[\u4e00-\u9fff]", report.markdown)
    assert all(not re.search(r"[\u4e00-\u9fff]", item.message) for item in report.limitations)


def test_deterministic_planner_uses_english_for_english_research(tmp_path):
    repository = SQLiteResearchRepository(tmp_path / "english-plan.db")
    control = ResearchControlPlane(repository, source_resolver=InMemoryDocumentResolver({
        "doc-a": {"doc_id": "doc-a", "title": "Agent delivery", "content": "Total Commits: 9"},
    }))
    job = control.create_job(ResearchRequest(query="Summarize Agent delivery.",
                                           source_scope=SourceScope(document_ids=["doc-a"])), user_id="english-test")
    plan = control.get_plan(job.research_id)
    assert plan.report_spec.language == "en-US"
    assert not re.search(r"[\u4e00-\u9fff]", json.dumps(plan.model_dump(mode="json"), ensure_ascii=False))
