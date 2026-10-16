from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

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


def test_default_acceptance_profile_is_english_and_preserves_frozen_source_scope():
    from eval import product_acceptance, research_product_acceptance
    root = Path(__file__).resolve().parents[3]
    assert product_acceptance.PROFILE == research_product_acceptance.PROFILE
    profile = json.loads(product_acceptance.PROFILE.read_text(encoding="utf-8"))
    current = json.loads((root/profile["source_dataset"]).read_text(encoding="utf-8"))
    original = json.loads((root/"eval/deep_research_a/datasets/cases.v1.json").read_text(encoding="utf-8"))
    current_by_id = {c["case_id"]:c for c in current["cases"]}
    original_by_id = {c["case_id"]:c for c in original["cases"]}
    for item in profile["cases"]:
        merged = {**current_by_id[item["source_case_id"]], **item}
        assert merged["language"] == "en-US"
        assert not re.search(r"[\u4e00-\u9fff]", merged["question"] + " ".join(merged["checks"]))
        for key in ("allowed_document_ids", "forbidden_document_ids", "key_source_locations"):
            assert merged[key] == original_by_id[item["source_case_id"]][key]


def test_research_acceptance_request_defaults_to_english():
    from eval.research_product_acceptance import run_research
    submitted = []
    def request(method, path, payload=None):
        if method == "POST":
            submitted.append(payload)
            return {"research_id":"english-default"}
        if path.endswith("/report"):
            return {"citations":[]}
        return {"status":"completed"}
    run_research(SimpleNamespace(request=request), {
        "question":"Summarize the source.", "source_scope":{"document_ids":["doc"]}
    }, "hybrid", 1)
    assert submitted[0]["report_spec"]["language"] == "en-US"


@pytest.mark.parametrize("mode", ["fast", "thinking"])
def test_boundary_probe_mode_is_explicit_for_english_questions(tmp_path, mode):
    from eval.integration_boundary_acceptance import BoundaryRun
    run = BoundaryRun.__new__(BoundaryRun)
    run.args = SimpleNamespace(output=tmp_path)
    message = {"id":"user-message", "role":"user", "parts":[{"type":"text", "text":"Read my personal library."}]}
    run.require_json = lambda user, method, path, **kwargs: {"id":"chat"} if method == "POST" else {"messages":[message]}
    bodies = []
    def call(user, method, path, **kwargs):
        bodies.append(kwargs["json"])
        return SimpleNamespace(status_code=200, text="", raise_for_status=lambda:None)
    run.call = call
    run.check = lambda *args, **kwargs:None
    run.ask("language-probe", "Read my personal library.", mode=mode)
    assert bodies[0]["weightMode"] == mode
