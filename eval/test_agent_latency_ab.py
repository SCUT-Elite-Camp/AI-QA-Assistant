from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryIntent, QueryPlan
from run_agent_latency_ab import _cohort_summary, _component_summary, _retrieval_latency_scope
from run_agent_eval import _aggregate_llm_metrics, evaluate_quality
from toolset.tool_layer.search_tool import SearchTool


def test_cohort_summary_reports_latency_quality_and_stage_metrics() -> None:
    rows = [
        {
            "latency_ms": 100,
            "expected_intent": "knowledge_qa",
            "actual_intent": "knowledge_qa",
            "fact_threshold_pass": True,
            "citation_valid": True,
            "expected_document_retrieved": True,
            "reference_quality_pass": None,
            "llm_metrics": {
                "call_count": 2,
                "total_ms": 80,
                "by_stage": {
                    "intent_classifier": {
                        "call_count": 1,
                        "failure_count": 0,
                        "total_ms": 30,
                    }
                },
            },
        },
        {
            "latency_ms": 200,
            "expected_intent": "knowledge_qa",
            "actual_intent": "comparison",
            "fact_threshold_pass": False,
            "citation_valid": True,
            "expected_document_retrieved": False,
            "reference_quality_pass": False,
            "llm_metrics": {
                "call_count": 3,
                "total_ms": 120,
                "by_stage": {
                    "intent_classifier": {
                        "call_count": 1,
                        "failure_count": 0,
                        "total_ms": 50,
                    }
                },
            },
        },
    ]

    summary = _cohort_summary(rows)

    assert summary["latency"]["mean_ms"] == 150
    assert summary["intent_accuracy"] == 0.5
    assert summary["fact_threshold_pass_rate"] == 0.5
    assert summary["citation_valid_rate"] == 1.0
    assert summary["expected_document_retrieved_rate"] == 0.5
    assert summary["reference_quality_pass_rate"] == 0.0
    assert summary["llm"]["mean_calls_per_request"] == 2.5
    assert summary["llm"]["stage_totals"]["intent_classifier"]["call_count"] == 2


def test_component_summary_reports_clarification_rewrite_and_compound_quality() -> None:
    summary = _component_summary([
        {
            "query_understanding_ms": 100,
            "expected_intent": "knowledge_qa",
            "intent_correct": True,
            "expected_clarification": True,
            "actual_clarification": True,
            "rewrite_term_recall": 0.5,
            "expected_parallel_target_count": 2,
            "sub_query_count_correct": True,
            "query_preparation_fallback": False,
            "llm_metrics": {"call_count": 1, "total_ms": 70, "by_stage": {}},
        },
        {
            "query_understanding_ms": 200,
            "expected_intent": "comparison",
            "intent_correct": False,
            "expected_clarification": False,
            "actual_clarification": True,
            "rewrite_term_recall": 1.0,
            "expected_parallel_target_count": None,
            "sub_query_count_correct": True,
            "query_preparation_fallback": True,
            "llm_metrics": {"call_count": 2, "total_ms": 120, "by_stage": {}},
        },
    ])

    assert summary["intent_accuracy"] == 0.5
    assert summary["clarification"]["f1"] == 2 / 3
    assert summary["mean_rewrite_term_recall"] == 0.75
    assert summary["compound_plan_accuracy"] == 1.0
    assert summary["query_preparation_fallback_rate"] == 0.5


def test_retrieval_scope_does_not_claim_production_environment() -> None:
    assert _retrieval_latency_scope("hybrid") == "configured_hybrid"
    assert _retrieval_latency_scope("bm25") == "controlled_non_hybrid"


def test_component_metric_aggregation_sums_calls_and_elapsed_time() -> None:
    result = _aggregate_llm_metrics([
        {"llm_metrics": {"call_count": 2, "total_ms": 70, "by_stage": {
            "clarifier": {"call_count": 1, "failure_count": 0, "total_ms": 20},
        }}},
        {"llm_metrics": {"call_count": 1, "total_ms": 40, "by_stage": {
            "clarifier": {"call_count": 0, "failure_count": 0, "total_ms": 0},
            "query_preparation": {"call_count": 1, "failure_count": 0, "total_ms": 40},
        }}},
    ])

    assert result["mean_calls_per_request"] == 1.5
    assert result["mean_llm_ms_per_request"] == 55
    assert result["stage_totals"]["clarifier"]["call_count"] == 1
    assert result["stage_totals"]["query_preparation"]["total_ms"] == 40


def test_quality_evaluator_accepts_bm25_mode_and_rejects_unknown_modes() -> None:
    report = evaluate_quality(
        [],
        repeats=1,
        use_judge=False,
        warmup_retrieval=False,
        retrieval_mode="bm25",
    )

    assert report["summary"]["run_count"] == 0

    try:
        evaluate_quality(
            [],
            repeats=1,
            use_judge=False,
            warmup_retrieval=False,
            retrieval_mode="unknown",
        )
    except ValueError as exc:
        assert "retrieval_mode" in str(exc)
    else:
        raise AssertionError("unknown retrieval modes must be rejected")


def test_full_agent_bm25_request_does_not_call_vector_search(monkeypatch) -> None:
    from agent.agent import Agent
    from agent.llm.llm_client import LLMClient

    class FixedQueryUnderstanding:
        def analyze(self, query, history=None, *, filters=None):
            return QueryPlan(
                original_query=query,
                standalone_query=query,
                intent=QueryIntent.KNOWLEDGE_QA,
            )

    def vector_search_must_not_run(*args, **kwargs):
        raise AssertionError("BM25 mode must not touch vector/Milvus search")

    monkeypatch.setattr(SearchTool, "_vector_search", vector_search_must_not_run)
    monkeypatch.setattr(
        SearchTool,
        "_bm25_search",
        lambda *args, **kwargs: [{
            "doc_id": "doc-bm25",
            "chunk_index": 0,
            "chunk_text": "QueryPlan stores the original user query.",
            "score": 0.95,
            "vector_score": 0.0,
            "bm25_score": 0.95,
        }],
    )
    monkeypatch.setattr(
        LLMClient,
        "chat",
        lambda *args, **kwargs: {
            "role": "assistant",
            "content": "QueryPlan stores the original user query [1].",
        },
    )

    agent = Agent(query_understanding=FixedQueryUnderstanding())  # type: ignore[arg-type]
    response = agent.chat(ChatRequest(
        query="Which field stores the original user query?",
        retrieval_mode="bm25",
        is_first_message=False,
    ))

    assert response.answer
    assert agent.last_run_result is not None
    assert agent.last_run_result.tool_calls
    assert agent.last_run_result.tool_calls[0].arguments["mode"] == "bm25"
