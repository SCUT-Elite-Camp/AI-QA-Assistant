"""CP2 Agent component, real-answer-quality and latency evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "agent", ROOT / "data-pipeline", ROOT / "data-persistence", ROOT / "toolset"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "agent" / ".env", override=False)
except ImportError:
    pass

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

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "agent_cp2_cases.json"
DEFAULT_REPORT_DIR = Path(__file__).parent / "reports"


def load_dataset(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for section in ("component_cases", "quality_cases"):
        if not isinstance(payload.get(section), list):
            raise ValueError(f"dataset section {section!r} must be a list")
    ids = [case.get("id") for section in ("component_cases", "quality_cases") for case in payload[section]]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("every case must have a unique non-empty id")
    return payload


def evaluate_components(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from agent.agent import Agent
    from agent.policy import IntentPolicyRouter

    # Reuse production Agent wiring so stage-specific model routing and
    # preparation fallback behavior are included in component A/B tests.
    understanding, router = Agent().query_understanding, IntentPolicyRouter()
    rows: list[dict[str, Any]] = []
    stage_samples = {"query_understanding": [], "policy_routing": []}
    for case in cases:
        query = case.get("online_query", case["query"])
        required_terms = case.get(
            "online_required_rewrite_terms",
            case.get("required_rewrite_terms", []),
        )
        fallback_before = understanding.query_preparation.fallback_attempts
        started = time.perf_counter()
        plan = understanding.analyze(query, case.get("history", []))
        understanding_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        policy = router.route(plan)
        policy_ms = (time.perf_counter() - started) * 1000
        stage_samples["query_understanding"].append(understanding_ms)
        stage_samples["policy_routing"].append(policy_ms)
        actual_intent = str(plan.intent)
        expected_sub_query_min = case.get("expected_sub_query_count_min")
        expected_sub_query_max = case.get("expected_sub_query_count_max")
        sub_query_count = len(plan.sub_queries)
        sub_query_count_correct = (
            (expected_sub_query_min is None or sub_query_count >= expected_sub_query_min)
            and (expected_sub_query_max is None or sub_query_count <= expected_sub_query_max)
        )
        rows.append({
            "id": case["id"], "query": query,
            "expected_intent": case["expected_intent"], "actual_intent": actual_intent,
            "intent_correct": actual_intent == case["expected_intent"],
            "intent_confidence": plan.intent_confidence,
            "expected_clarification": case["should_clarify"],
            "actual_clarification": plan.needs_clarification,
            "clarification_correct": plan.needs_clarification == case["should_clarify"],
            "clarification_question": plan.clarification_question,
            "ambiguity_reason": plan.ambiguity_reason,
            "expected_follow_up": case.get("expected_follow_up"), "actual_follow_up": plan.is_follow_up,
            "expected_clarification_reply": case.get("expected_clarification_reply"),
            "actual_clarification_reply": plan.is_clarification_reply,
            "rewrite_term_recall": required_term_recall(plan.standalone_query, required_terms),
            "standalone_query": plan.standalone_query,
            "sub_queries": plan.sub_queries,
            "filters": plan.filters,
            "expected_stages": case.get("expected_stages", []),
            "expected_stop_reason": case.get("expected_stop_reason"),
            "expected_tool_calls": case.get("expected_tool_calls"),
            "expected_sub_query_count_min": expected_sub_query_min,
            "expected_sub_query_count_max": expected_sub_query_max,
            "expected_parallel_target_count": case.get("expected_parallel_target_count"),
            "sub_query_count": sub_query_count,
            "sub_query_count_correct": sub_query_count_correct,
            "query_preparation_fallback": (
                understanding.query_preparation.fallback_attempts > fallback_before
            ),
            "policy": policy.model_dump(mode="json"),
            "query_understanding_ms": round(understanding_ms, 2), "policy_routing_ms": round(policy_ms, 2),
        })
    return {"summary": {
        "case_count": len(rows),
        "intent_accuracy": sum(row["intent_correct"] for row in rows) / len(rows) if rows else 0.0,
        "clarification": binary_scores([r["expected_clarification"] for r in rows], [r["actual_clarification"] for r in rows]),
        "mean_rewrite_term_recall": sum(r["rewrite_term_recall"] for r in rows) / len(rows) if rows else 0.0,
        "compound_plan_accuracy": (
            sum(r["sub_query_count_correct"] for r in rows if r["expected_parallel_target_count"] is not None)
            / sum(r["expected_parallel_target_count"] is not None for r in rows)
            if any(r["expected_parallel_target_count"] is not None for r in rows)
            else 0.0
        ),
        "query_preparation_fallback_rate": (
            sum(r["query_preparation_fallback"] for r in rows) / len(rows)
            if rows
            else 0.0
        ),
        "predicted_intents": dict(Counter(r["actual_intent"] for r in rows)),
        "latency": {name: latency_summary(values) for name, values in stage_samples.items()},
    }, "cases": rows}


def _evidence_text(agent: Any) -> str:
    result = agent.last_run_result
    return "\n".join(str(item.get("content") or item.get("snippet") or item.get("text") or "") for item in (result.evidence if result else []))


def _aggregate_llm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stage_totals: dict[str, dict[str, int | float]] = {}
    call_counts: list[int] = []
    latency_totals: list[float] = []
    for row in rows:
        metrics = row.get("llm_metrics") or {}
        call_counts.append(int(metrics.get("call_count", 0)))
        latency_totals.append(float(metrics.get("total_ms", 0.0)))
        for name, values in (metrics.get("by_stage") or {}).items():
            stage = stage_totals.setdefault(
                name,
                {"call_count": 0, "failure_count": 0, "total_ms": 0.0},
            )
            stage["call_count"] += int(values.get("call_count", 0))
            stage["failure_count"] += int(values.get("failure_count", 0))
            stage["total_ms"] = round(
                float(stage["total_ms"]) + float(values.get("total_ms", 0.0)), 2
            )
    return {
        "mean_calls_per_request": round(sum(call_counts) / len(call_counts), 2) if call_counts else 0.0,
        "mean_llm_ms_per_request": round(sum(latency_totals) / len(latency_totals), 2) if latency_totals else 0.0,
        "stage_totals": stage_totals,
    }


def evaluate_quality(cases: list[dict[str, Any]], repeats: int, use_judge: bool, warmup_retrieval: bool = True) -> dict[str, Any]:
    from agent.agent import Agent
    from agent.schemas.chat import ChatRequest
    if use_judge:
        from metrics import evaluate_answer_relevance, evaluate_faithfulness

    agent, rows, all_latencies = Agent(), [], []
    if warmup_retrieval:
        search_tool = agent.registry.get_tool("search_documents")
        if search_tool is not None and hasattr(search_tool, "search"):
            search_tool.search("financial report", top_k=1, mode="vector")
    for repeat in range(repeats):
        for case in cases:
            query = case.get("online_query", case["query"])
            request = ChatRequest(query=query, session_id=f"eval-{case['id']}-{repeat}-{uuid.uuid4().hex[:8]}", is_first_message=False)
            started = time.perf_counter()
            response = agent.chat(request)
            latency_ms = (time.perf_counter() - started) * 1000
            all_latencies.append(latency_ms)
            result, orchestration = agent.last_run_result, agent.last_orchestration
            required_facts = case.get("required_facts", [])
            coverage, fact_hits = required_fact_coverage(response.answer, required_facts)
            fact_match_details = required_fact_match_details(response.answer, required_facts)
            citation_check = agent.last_citation_check
            citation_threshold_pass = len(response.citations) >= case.get("min_citations", 0)
            public_citations = [citation.model_dump(mode="json") for citation in response.citations]
            accepted_evidence = list(result.evidence if result else [])
            reference_match = reference_answer_match(response.answer, case.get("reference_answer", "")) if case.get("reference_answer") else None
            reference_f1 = reference_token_f1(response.answer, case.get("reference_answer", "")) if case.get("reference_answer") else None
            reference_recall = reference_token_recall(response.answer, case.get("reference_answer", "")) if case.get("reference_answer") else None
            row = {
                "id": case["id"], "repeat": repeat + 1, "query": query, "status": str(response.status),
                "answer": response.answer, "answer_length": len(response.answer), "expected_intent": case.get("expected_intent"),
                "actual_intent": str(orchestration.query_plan.intent) if orchestration else None,
                "intent_confidence": orchestration.query_plan.intent_confidence if orchestration else None,
                "standalone_query": orchestration.query_plan.standalone_query if orchestration else None,
                "needs_clarification": orchestration.query_plan.needs_clarification if orchestration else None,
                "clarification_question": orchestration.query_plan.clarification_question if orchestration else "",
                "ambiguity_reason": orchestration.query_plan.ambiguity_reason if orchestration else "",
                "is_follow_up": orchestration.query_plan.is_follow_up if orchestration else None,
                "is_clarification_reply": orchestration.query_plan.is_clarification_reply if orchestration else None,
                "sub_queries": orchestration.query_plan.sub_queries if orchestration else [],
                "query_filters": orchestration.query_plan.filters if orchestration else {},
                "intent_policy": orchestration.policy.model_dump(mode="json") if orchestration else {},
                "target_stages": case.get("target_stages", []),
                "fact_coverage": coverage, "fact_hits": fact_hits,
                "fact_match_details": fact_match_details,
                "fact_threshold_pass": sum(fact_hits) >= case.get("min_fact_groups", len(fact_hits)),
                "citation_count": len(response.citations), "citation_threshold_pass": citation_threshold_pass,
                "citation_valid": citation_threshold_pass and bool(citation_check.valid) if citation_check else False,
                "public_citations": public_citations,
                "reference_answer_match": reference_match,
                "reference_token_f1": reference_f1,
                "reference_token_recall": reference_recall,
                "reference_quality_pass": reference_quality_pass(response.answer, case["reference_answer"]) if reference_recall is not None else None,
                "expected_document_hit": expected_document_hit(public_citations, case.get("expected_doc_names", [])),
                "expected_document_retrieved": expected_document_hit(
                    accepted_evidence,
                    case.get("expected_doc_names", []),
                ),
                "stop_reason": str(result.stop_reason) if result else None, "iterations": result.iterations if result else 0,
                "error_code": result.error_code if result else None,
                "retrieval_attempts": result.retrieval_attempts if result else 0, "tool_call_count": len(result.tool_calls) if result else 0,
                "tool_calls": [record.model_dump(mode="json") for record in result.tool_calls] if result else [],
                "evidence_gate_reason": result.evidence_gate_reason if result else "",
                "covered_evidence_targets": result.covered_evidence_targets if result else [],
                "missing_evidence_targets": result.missing_evidence_targets if result else [],
                "eligible_evidence_count": result.eligible_evidence_count if result else 0,
                "rejected_evidence_count": result.rejected_evidence_count if result else 0,
                "answer_completeness_checked": result.answer_completeness_checked if result else False,
                "answer_complete_before_repair": result.answer_complete if result else None,
                "missing_answer_aspects": result.missing_answer_aspects if result else [],
                "missing_critical_facts": result.missing_critical_facts if result else [],
                "answer_repair_attempted": result.answer_repair_attempted if result else False,
                "llm_metrics": result.llm_metrics if result else {},
                "evidence_items": [
                    {
                        "title": item.get("title"),
                        "doc_id": item.get("doc_id"),
                        "score": item.get("score"),
                        "retrieval_query": item.get("retrieval_query"),
                        "content_preview": str(item.get("content") or "")[:500],
                    }
                    for item in (result.evidence if result else [])
                ],
                "latency_ms": round(latency_ms, 2),
            }
            if use_judge:
                row["judge_relevance"] = evaluate_answer_relevance(response.answer, query)
                row["judge_faithfulness"] = evaluate_faithfulness(response.answer, _evidence_text(agent))
            rows.append(row)
    return {"summary": {
        "run_count": len(rows), "success_rate": sum(bool(r["answer"]) for r in rows) / len(rows) if rows else 0.0,
        "intent_accuracy": sum(r["actual_intent"] == r["expected_intent"] for r in rows) / len(rows) if rows else 0.0,
        "fact_threshold_pass_rate": sum(r["fact_threshold_pass"] for r in rows) / len(rows) if rows else 0.0,
        "citation_threshold_pass_rate": sum(r["citation_threshold_pass"] for r in rows) / len(rows) if rows else 0.0,
        "citation_valid_rate": sum(r["citation_valid"] for r in rows) / len(rows) if rows else 0.0,
        "reference_answer_match_rate": sum(r["reference_answer_match"] is True for r in rows) / sum(r["reference_answer_match"] is not None for r in rows) if any(r["reference_answer_match"] is not None for r in rows) else None,
        "mean_reference_token_f1": sum(r["reference_token_f1"] for r in rows if r["reference_token_f1"] is not None) / sum(r["reference_token_f1"] is not None for r in rows) if any(r["reference_token_f1"] is not None for r in rows) else None,
        "reference_quality_pass_rate": sum(r["reference_quality_pass"] is True for r in rows) / sum(r["reference_quality_pass"] is not None for r in rows) if any(r["reference_quality_pass"] is not None for r in rows) else None,
        "expected_document_hit_rate": sum(r["expected_document_hit"] for r in rows) / len(rows) if rows else 0.0,
        "expected_document_retrieved_rate": sum(r["expected_document_retrieved"] for r in rows) / len(rows) if rows else 0.0,
        "repeated_tool_call_rate": sum(r["stop_reason"] == "repeated_tool_call" for r in rows) / len(rows) if rows else 0.0,
        "policy_limit_rate": sum(r["stop_reason"] == "policy_limit" for r in rows) / len(rows) if rows else 0.0,
        "answer_completeness_check_rate": sum(r["answer_completeness_checked"] for r in rows) / len(rows) if rows else 0.0,
        "answer_repair_rate": sum(r["answer_repair_attempted"] for r in rows) / len(rows) if rows else 0.0,
        "llm": _aggregate_llm_metrics(rows),
        "stop_reasons": dict(Counter(r["stop_reason"] for r in rows)),
        "latency": latency_summary(all_latencies),
    }, "cases": rows}


def save_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for suite_name in ("components", "quality", "compound"):
        cases = report.get(suite_name, {}).get("cases", [])
        if cases:
            csv_path = output.with_name(f"{output.stem}_{suite_name}.csv")
            keys = [key for key, value in cases[0].items() if not isinstance(value, (dict, list))]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=keys)
                writer.writeheader(); writer.writerows({key: row.get(key) for key in keys} for row in cases)


def main() -> int:
    parser = argparse.ArgumentParser(description="CP2 Agent evaluation")
    parser.add_argument("--suite", choices=("components", "quality", "compound", "all"), default="components")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--online", action="store_true", help="confirm real model/API usage")
    parser.add_argument("--judge", action="store_true", help="two extra judge calls per quality run")
    parser.add_argument("--retrieval-namespace", help="isolated index name, e.g. financebench_eval")
    parser.add_argument("--limit", type=int, help="run only the first N cases for a low-cost smoke baseline")
    parser.add_argument("--case-id", action="append", help="run only the named case id; may be repeated")
    parser.add_argument("--no-retrieval-warmup", action="store_true", help="include retrieval cold start in measured requests")
    parser.add_argument("--repeats", type=int, default=1); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.online:
        raise SystemExit("This evaluation invokes the configured model. Re-run with --online to confirm API usage.")
    if args.judge and args.suite == "components": raise SystemExit("--judge requires quality, compound, or all")
    if args.repeats < 1: raise SystemExit("--repeats must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.retrieval_namespace:
        if not args.retrieval_namespace.replace("_", "").isalnum():
            raise SystemExit("--retrieval-namespace must contain only letters, digits, and underscores")
        namespace_dir = ROOT / "data-persistence" / "data" / "namespaces" / args.retrieval_namespace
        os.environ["RETRIEVAL_COLLECTION"] = f"{args.retrieval_namespace}_chunks"
        os.environ["RETRIEVAL_DOCUMENTS_DIR"] = str(namespace_dir / "documents")
        os.environ["RETRIEVAL_BM25_PATH"] = str(namespace_dir / "bm25_index.pkl")
    dataset = load_dataset(args.dataset)
    report: dict[str, Any] = {"metadata": {"created_at": datetime.now().astimezone().isoformat(), "suite": args.suite,
        "dataset": str(args.dataset), "model": os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME") or "configured-default",
        "judge_enabled": args.judge, "repeats": args.repeats,
        "retrieval_namespace": args.retrieval_namespace or "default"}}
    component_cases = dataset["component_cases"]
    quality_cases = dataset["quality_cases"]
    if args.case_id:
        selected_ids = set(args.case_id)
        component_cases = [case for case in component_cases if case["id"] in selected_ids]
        quality_cases = [case for case in quality_cases if case["id"] in selected_ids]
        if not component_cases and not quality_cases:
            raise SystemExit("none of the requested --case-id values exist in the dataset")
    if args.limit:
        component_cases = component_cases[:args.limit]
        quality_cases = quality_cases[:args.limit]
    if args.suite in ("components", "all"): report["components"] = evaluate_components(component_cases)
    if args.suite in ("quality", "all"): report["quality"] = evaluate_quality(quality_cases, args.repeats, args.judge, not args.no_retrieval_warmup)
    if args.suite == "compound":
        compound_cases = [
            {
                **case,
                "min_citations": case.get("min_citations", 1),
            }
            for case in component_cases
            if case["id"].startswith("local_compound_")
        ]
        report["compound"] = evaluate_quality(
            compound_cases,
            args.repeats,
            args.judge,
            not args.no_retrieval_warmup,
        )
    output = args.output or DEFAULT_REPORT_DIR / f"agent_cp2_{datetime.now():%Y%m%d_%H%M%S}.json"
    save_report(report, output)
    print(json.dumps({"report": str(output), "summary": {k: v["summary"] for k, v in report.items() if k != "metadata"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
