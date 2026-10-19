import json
from types import SimpleNamespace

import pytest

from eval import product_acceptance as acceptance
from eval.summarize_product_acceptance import failure_hint, summarize
from eval.deep_research_benchmark import _case_scope
from deep_research.model_client import ResearchModelClient
from deep_research.tools import LocalJsonSearchBackend
from agent.schemas.research import ResearchPlanValidator, ResearchReport, ResearchCitation, ResearchResultStatus


def test_profile_is_representative_and_checks_are_pointwise():
    profile = acceptance.load(acceptance.PROFILE)
    assert len(profile["cases"]) == 7
    assert len({c["scenario"] for c in profile["cases"]}) == 7
    assert all(len(c["checks"]) >= 2 for c in profile["cases"])
    assert "pending" in profile["review_status"]


def test_judge_thinking_payload_follows_runtime_configuration(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "enabled")
    assert acceptance._thinking_payload() == {"type": "enabled"}
    monkeypatch.setenv("LLM_THINKING_MODE", "disabled")
    assert acceptance._thinking_payload() == {"type": "disabled"}
    monkeypatch.delenv("LLM_THINKING_MODE")
    assert acceptance._thinking_payload() is None


def test_answer_only_run_skips_llm_judge(monkeypatch, tmp_path):
    client = SimpleNamespace(request=lambda *args, **kwargs: {
        "status": "success", "answer": "answer", "citations": []
    })
    monkeypatch.setattr(acceptance, "judge", lambda *args: pytest.fail("judge must not run"))
    monkeypatch.setattr(acceptance, "score_sources", lambda *args: {
        "out_of_scope_count": 0, "locator_excerpt_valid_rate": None
    })
    record = acceptance.run_one(client, {
        "case_id": "PA-TEST", "question": "q", "checks": ["c"],
        "allowed_document_ids": ["a"]
    }, "G1", 1, tmp_path, skip_judge=True)
    assert record["runtime_ok"] is True
    assert record["judge"] is None
    assert record["accepted"] is None


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


def test_excerpt_scoring_accepts_adjacent_chunk_expansion_from_same_document():
    case = {"judge_sources": [{"doc_id": "a", "content": "first section second section", "chunks": [
                {"chunk_id": "a_chunk_0", "text": "first section"},
                {"chunk_id": "a_chunk_1", "text": "second section"},
            ]}],
            "allowed_document_ids": ["a"],
            "key_source_locations": [{"doc_id": "a", "chunk_id": "a_chunk_1"}]}
    result = acceptance.score_sources(case, {"citations": [{
        "doc_id": "a", "chunk_id": "a_chunk_1",
        "snippet": "first section second section",
    }]})
    assert result["locator_excerpt_valid_rate"] == 1.0
    assert result["key_location_recall"] == 1.0


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


def source_report():
    return ResearchReport(report_id="r", research_id="job", markdown="source fallback", result_status=ResearchResultStatus.COMPLETE,
                          citations=[ResearchCitation(number=1, evidence_id="e", doc_id="a", title="source", locator="a_chunk_0", excerpt="source fact", content_hash="12345678")])


@pytest.mark.parametrize("body,reason", [("[0]", "stop"), ("[2]", "stop"), ("[1]", "length")])
def test_report_guard_rejects_invalid_citations_and_truncation(body, reason):
    assert ResearchModelClient._structural_issues(valid_report().replace("[1]", body), 1, reason)


def test_chinese_report_heading_language_capability():
    content = "### 1. 结论摘要\n正文 [1]\n**关键发现**\n正文 [1]"
    normalized = ResearchModelClient._normalize_section_headings(content, "zh-CN")
    assert "## 结论摘要\n" in normalized
    assert "## 关键发现\n" in normalized


def test_comparison_periods_are_not_duplicate_tasks():
    left = "Check 2026-W30 Agent total commits, new features, bug fixes and other improvements"
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
