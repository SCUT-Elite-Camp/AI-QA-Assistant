"""Offline metrics for the bounded Agent quality runner."""
from run_agent_eval import _aggregate_llm_metrics, evaluate_quality


def test_component_metric_aggregation_sums_calls_and_elapsed_time() -> None:
    result = _aggregate_llm_metrics([
        {"llm_metrics": {"call_count": 2, "total_ms": 70, "by_stage": {
            "agent_runtime": {"call_count": 1, "failure_count": 0, "total_ms": 20},
        }}},
        {"llm_metrics": {"call_count": 1, "total_ms": 40, "by_stage": {
            "agent_runtime": {"call_count": 0, "failure_count": 0, "total_ms": 0},
            "answer_generation_fast": {"call_count": 1, "failure_count": 0, "total_ms": 40},
        }}},
    ])

    assert result["mean_calls_per_request"] == 1.5
    assert result["mean_llm_ms_per_request"] == 55
    assert result["stage_totals"]["agent_runtime"]["call_count"] == 1
    assert result["stage_totals"]["answer_generation_fast"]["total_ms"] == 40


def test_quality_evaluator_accepts_bm25_mode_and_rejects_unknown_modes() -> None:
    report = evaluate_quality(
        [],
        repeats=1,
        use_judge=False,
        retrieval_mode="bm25",
    )

    assert report["summary"]["run_count"] == 0

    try:
        evaluate_quality(
            [],
            repeats=1,
            use_judge=False,
                retrieval_mode="unknown",
        )
    except ValueError as exc:
        assert "retrieval_mode" in str(exc)
    else:
        raise AssertionError("unknown retrieval modes must be rejected")
