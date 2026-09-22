import json
from types import SimpleNamespace

import pytest

from eval import product_acceptance as acceptance
from eval.summarize_product_acceptance import failure_hint, summarize
from eval.deep_research_benchmark import _case_scope
from deep_research.model_report import EvidenceReportSynthesizer
from deep_research.renderer import MarkdownReportRenderer
from deep_research.tools import LocalJsonSearchBackend
from deep_research.planner import ModelResearchPlanner
from agent.config.settings import settings
from agent.schemas.research import ResearchRequest, SourceScope, ResearchPlanValidator
from agent.orchestration.orchestrator import AgentOrchestrator
from agent.schemas.chat import ChatRequest
from agent.schemas.intent_policy import IntentPolicy
from agent.policy import IntentPolicyRouter
from agent.schemas.query_plan import QueryIntent, QueryPlan


def test_profile_is_representative_and_checks_are_pointwise():
    profile = acceptance.load(acceptance.PROFILE)
    assert len(profile["cases"]) == 7
    assert len({c["scenario"] for c in profile["cases"]}) == 7
    assert all(len(c["checks"]) >= 2 for c in profile["cases"])
    assert "pending" in profile["review_status"]


def test_explicit_acceptance_scope_does_not_expand_to_whole_space():
    scope = _case_scope({"case_id": "PA-001", "source_manifest": "manifest:DR-A-010",
                         "source_scope": {"document_ids": ["a"], "knowledge_base_ids": []}})
    assert scope == {"document_ids": ["a"], "knowledge_base_ids": [], "topic": ""}


def test_excerpt_scoring_rejects_wrong_section_and_out_of_scope():
    case = {"judge_sources": [{"doc_id": "a", "chunks": [{"chunk_id": "a_chunk_1", "text": "correct section"}]}],
            "allowed_document_ids": ["a"], "key_source_locations": [{"doc_id": "a", "chunk_id": "a_chunk_1"}]}
    result = acceptance.score_sources(case, {"citations": [
        {"doc_id": "a", "chunk_id": "a_chunk_1", "snippet": "wrong section"},
        {"doc_id": "b", "chunk_id": "b_chunk_1", "snippet": "correct section"}]})
    assert result["valid_excerpt_count"] == 0
    assert result["out_of_scope_count"] == 1


def test_search_returns_multiple_sections_and_keeps_document_diversity(tmp_path):
    for doc_id in ("a", "b", "outside"):
        (tmp_path / f"{doc_id}.json").write_text(json.dumps({"doc_id": doc_id, "chunks": [
            {"text": "release summary total", "index": 0},
            {"text": "release changed files", "index": 1},
            {"text": "unrelated text", "index": 2}]}), encoding="utf-8")
    rows = LocalJsonSearchBackend(tmp_path).search("release summary files", filters={"doc_ids": ["a", "b"]}, top_k=4)
    assert [r["doc_id"] for r in rows] == ["a", "b", "a", "b"]
    assert {r["chunk_id"] for r in rows} == {"a_chunk_0", "a_chunk_1", "b_chunk_0", "b_chunk_1"}


def test_document_title_does_not_swamp_section_and_filename_terms(tmp_path):
    title = "Sprint Weekly Agent Module Deliverables Summary"
    (tmp_path / "a.json").write_text(json.dumps({"doc_id": "a", "title": title, "chunks": [
        {"text": title, "index": 0},
        {"text": "Impacted Code Files ADDED agent/query/intent_classifier.py", "index": 1}]}), encoding="utf-8")
    rows = LocalJsonSearchBackend(tmp_path).search(title + " impacted files intent classifier", top_k=1)
    assert rows[0]["chunk_id"] == "a_chunk_1"


def valid_report():
    return "\n\n".join(f"## Section {i}\nA supported statement with sufficient explanation from the original evidence. [1]" for i in range(5))


@pytest.mark.parametrize("body,reason", [("[0]", "stop"), ("[2]", "stop"), ("[1]", "length")])
def test_report_guard_rejects_invalid_citations_and_truncation(body, reason):
    assert EvidenceReportSynthesizer._structural_issues(valid_report().replace("[1]", body), 1, reason)


def test_report_normalizes_known_markdown_headings():
    content = "### 1. 结论摘要\n正文 [1]\n**关键发现**\n正文 [1]"
    normalized = EvidenceReportSynthesizer._normalize_section_headings(content, "zh-CN")
    assert "## 结论摘要\n" in normalized
    assert "## 关键发现\n" in normalized


def test_report_repair_is_bounded_and_preserves_fallback(monkeypatch):
    base = SimpleNamespace(citations=[SimpleNamespace(number=1, title="source", document_version="1", locator="a_chunk_0", excerpt="source fact")])
    monkeypatch.setattr(MarkdownReportRenderer, "render", lambda *args, **kwargs: base)
    synth = EvidenceReportSynthesizer(api_base="https://example.invalid", api_key="test", model="test")
    calls = []
    def chat(payload):
        calls.append(json.loads(json.dumps(payload)))
        return {"choices": [{"message": {"content": "incomplete [0]"}, "finish_reason": "length"}]}
    monkeypatch.setattr(synth, "_chat", chat)
    assert synth.render(objective="question") is base
    assert len(calls) == 2
    assert "same evidence" in calls[1]["messages"][-1]["content"]


def test_report_accepts_complete_repair(monkeypatch):
    base = SimpleNamespace(citations=[SimpleNamespace(number=1, title="source", document_version="1", locator="a_chunk_0", excerpt="source fact")],
                           model_copy=lambda update: update)
    monkeypatch.setattr(MarkdownReportRenderer, "render", lambda *args, **kwargs: base)
    synth = EvidenceReportSynthesizer(api_base="https://example.invalid", api_key="test", model="test")
    replies = iter(["incomplete", valid_report()])
    monkeypatch.setattr(synth, "_chat", lambda payload: {"choices": [{"message": {"content": next(replies)}, "finish_reason": "stop"}]})
    assert "## Sources" in synth.render(objective="question")["markdown"]


def test_research_planner_honors_configured_thinking_mode(monkeypatch):
    monkeypatch.setattr(settings, "LLM_THINKING_MODE", "disabled")
    planner = ModelResearchPlanner(api_base="https://example.invalid", api_key="test", model="test")
    calls = []
    def chat(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": json.dumps({"tasks": [
            {"question": "Find facts", "purpose": "Read source", "acceptance_target": "Facts supported"},
            {"question": "Check limits", "purpose": "Read limits", "acceptance_target": "Limits supported"}]})}}]}
    monkeypatch.setattr(planner, "_chat", chat)
    manifest = SimpleNamespace(documents=[SimpleNamespace(doc_id="a", title="doc", source_type="confluence", version="1", effective_at=None)])
    tasks = planner._generate_tasks(ResearchRequest(query="Explain facts", source_scope=SourceScope(document_ids=["a"])), manifest)
    assert len(tasks) == 2
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_long_conflict_summary_is_bounded_without_modifying_evidence():
    original = "long source statement " * 300
    summary = MarkdownReportRenderer._bounded_summary(original)
    assert len(summary) == 2000
    assert summary.endswith("…")
    assert len(original) > 2000


def test_comparison_periods_are_not_duplicate_tasks():
    left = "核对2026-W30的Agent模块总提交新功能Bug修复其他改进数量"
    right = left.replace("W30", "W34")
    assert not ResearchPlanValidator._questions_duplicate(left, right)
    assert ResearchPlanValidator._questions_duplicate(left, left)


def test_acceptance_summary_does_not_hide_failures_or_conflate_runtime_and_quality():
    rows = [
        {"group": "G1", "accepted": True, "runtime_ok": True, "latency_seconds": 2},
        {"group": "G1", "accepted": False, "runtime_ok": True, "latency_seconds": 4,
         "source_metrics": {"key_location_recall": 0.5}},
        {"group": "G2", "accepted": False, "error": "judge error"},
    ]
    result = summarize(rows)
    assert result["G1"]["runs"] == 2
    assert result["G1"]["accepted"] == 1
    assert result["G1"]["runtime_ok"] == 2
    assert result["G1"]["median_response_seconds"] == 3
    assert failure_hint(rows[2]) == "evaluation_or_transport_error"


def test_hard_document_scope_widens_section_retrieval_within_policy_cap():
    policy = IntentPolicy(top_k=10)
    mode, top_k = AgentOrchestrator._effective_retrieval_options(
        ChatRequest(query="q", top_k=5, filters={"doc_ids": ["doc-a"]}), policy
    )
    assert mode == "hybrid"
    assert top_k == 10
    assert IntentPolicyRouter().route(QueryPlan(
        original_query="q", standalone_query="q", intent=QueryIntent.KNOWLEDGE_QA
    )).top_k == 10
