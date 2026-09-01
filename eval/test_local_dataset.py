import json
from pathlib import Path


DATASET = Path(__file__).parent / "datasets" / "agent_cp2_cases.json"


def _load() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_local_core_regression_has_twenty_seven_unique_cases() -> None:
    dataset = _load()
    cases = dataset["component_cases"] + dataset["quality_cases"]

    assert dataset["metadata"]["case_count"] == 27
    assert len(cases) == 27
    assert len({case["id"] for case in cases}) == 27


def test_compound_comparison_cases_cover_parallel_task_shapes() -> None:
    cases = [
        case
        for case in _load()["component_cases"]
        if case["id"].startswith("local_compound_")
    ]

    assert len(cases) == 5
    assert all(case["expected_intent"] == "comparison" for case in cases)
    assert all("parallel_retrieval" in case["expected_stages"] for case in cases)
    assert {case["expected_parallel_target_count"] for case in cases} == {2, 3}
    assert all(case["expected_sub_query_count_min"] >= 2 for case in cases)


def test_component_cases_cover_all_frozen_intents() -> None:
    intents = {case["expected_intent"] for case in _load()["component_cases"]}

    assert intents == {
        "knowledge_qa",
        "document_search",
        "summarization",
        "comparison",
        "casual_chat",
        "system_help",
        "unsupported",
    }


def test_component_cases_cover_query_understanding_and_control_paths() -> None:
    cases = _load()["component_cases"]
    stages = {
        stage
        for case in cases
        for stage in case.get("expected_stages", [])
    }

    assert any(case.get("should_clarify") is True for case in cases)
    assert any(case.get("expected_follow_up") is True for case in cases)
    assert any(case.get("expected_tool_calls") == 0 for case in cases)
    assert {
        "conversation_memory",
        "reference_resolution",
        "intent_classifier",
        "clarifier",
        "query_rewriter",
        "query_planner",
        "policy_routing",
    } <= stages


def test_quality_cases_are_grounded_and_cover_answer_pipeline() -> None:
    dataset = _load()
    quality_cases = dataset["quality_cases"]
    source_names = {
        Path(source).stem.casefold()
        for source in dataset["metadata"]["source_documents"]
    }
    stages = {
        stage
        for case in quality_cases
        for stage in case.get("target_stages", [])
    }

    assert len(quality_cases) == 8
    for case in quality_cases:
        assert case["required_facts"]
        assert case["min_fact_groups"] <= len(case["required_facts"])
        assert case["min_citations"] >= 1
        assert case["expected_doc_names"]
        assert any(
            expected.casefold() in source
            or source in expected.casefold()
            for expected in case["expected_doc_names"]
            for source in source_names
        )

    assert {
        "tool_execution",
        "evidence_gate",
        "corrective_retrieval",
        "answer_generation",
        "answer_completeness",
        "citation_check",
    } <= stages
