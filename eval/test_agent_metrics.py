import json
from pathlib import Path

from agent_metrics import (
    binary_scores,
    expected_document_hit,
    latency_summary,
    reference_answer_match,
    reference_quality_pass,
    reference_token_f1,
    reference_token_recall,
    required_fact_coverage,
    required_fact_match_details,
    required_term_recall,
)
from run_agent_eval import load_dataset
from ingest_financebench import namespace_paths


def test_binary_scores_are_explainable():
    assert binary_scores([True, True, False, False], [True, False, True, False]) == {
        "precision": 0.5, "recall": 0.5, "f1": 0.5, "accuracy": 0.5,
        "tp": 1, "fp": 1, "fn": 1, "tn": 1,
    }


def test_latency_summary_includes_tail_latency():
    summary = latency_summary([10, 20, 30, 40, 100])
    assert summary["count"] == 5
    assert summary["p50_ms"] == 30
    assert summary["p95_ms"] == 88
    assert summary["max_ms"] == 100


def test_fact_and_rewrite_coverage():
    coverage, hits = required_fact_coverage("ToolExecutor 校验参数并执行工具", [["参数"], ["执行"], ["引用"]])
    assert coverage == 2 / 3
    assert hits == [True, True, False]
    assert required_term_recall("比较 CP1 与 CP2", ["CP1", "CP2"]) == 1.0


def test_fact_matching_normalizes_identifier_formatting_and_reports_reason():
    answer = "Citation Checker validates the standalone query and accepted evidence."
    groups = [["CitationChecker"], ["standalone_query"], ["missing_targets"]]

    coverage, hits = required_fact_coverage(answer, groups)
    details = required_fact_match_details(answer, groups)

    assert coverage == 2 / 3
    assert hits == [True, True, False]
    assert details[0]["match_type"] == "normalized_alias"
    assert details[1]["match_type"] == "identifier_tokens"
    assert details[2]["matched_term"] is None


def test_committed_dataset_is_valid():
    dataset = load_dataset(Path(__file__).parent / "datasets" / "agent_cp2_cases.json")
    assert len(dataset["component_cases"]) >= 14
    assert len(dataset["quality_cases"]) >= 6


def test_financebench_manifest_is_valid_when_present():
    path = Path(__file__).parent / "datasets" / "financebench_agent_cases.json"
    if not path.exists():
        return
    dataset = load_dataset(path)
    assert len(dataset["quality_cases"]) == 20
    assert all(case["expected_evidence"] for case in dataset["quality_cases"])
    assert all(case["expected_doc_names"] for case in dataset["quality_cases"])


def test_financial_reference_answer_normalization():
    assert reference_answer_match("Capital expenditure was $1,577.00 million.", "$1577.00")
    assert not reference_answer_match("Capital expenditure was $1,377 million.", "$1577.00")
    assert reference_token_f1("Amcor operates in the global packaging industry.", "Amcor is a global leader in packaging production.") > 0.3
    assert reference_token_recall("Amcor operates in the global packaging industry.", "Amcor is a global leader in packaging production.") >= 0.5
    assert reference_token_recall("I cannot confirm which securities are registered.", "There are none") == 0.0
    assert not reference_quality_pass(
        "Boeing serves commercial airlines and the US government.",
        "Boeing serves commercial airlines and the US government, which represented 40% of revenue.",
    )
    assert reference_quality_pass(
        "The US government represented 40% of revenue.",
        "The US government represented 40% of revenue.",
    )


def test_expected_document_hit_uses_public_citation_fields():
    citations = [{"title": "3M_2018_10K.pdf", "doc_id": "hash", "source_url": None}]
    assert expected_document_hit(citations, ["3M_2018_10K"])
    assert not expected_document_hit(citations, ["AMD_2022_10K"])


def test_financebench_namespace_is_isolated():
    documents, bm25, collection = namespace_paths("financebench_eval")
    assert "namespaces" in documents.parts
    assert documents.name == "documents"
    assert bm25.name == "bm25_index.pkl"
    assert collection == "financebench_eval_chunks"


def test_duplicate_case_ids_are_rejected(tmp_path):
    dataset = tmp_path / "bad.json"
    dataset.write_text(json.dumps({"component_cases": [{"id": "same"}], "quality_cases": [{"id": "same"}]}), encoding="utf-8")
    try:
        load_dataset(dataset)
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate ids should fail validation")
