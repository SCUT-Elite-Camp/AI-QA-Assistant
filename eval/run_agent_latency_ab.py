"""Paired end-to-end latency A/B for the cascaded QueryUnderstanding path.

This evaluator changes no production defaults. BM25 is the default because it
can run without Milvus; its retrieval latency must not be read as production
hybrid latency.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "agent", ROOT / "data-pipeline", ROOT / "data-persistence", ROOT / "toolset"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "agent" / ".env", override=False)
except ImportError:
    pass

from agent_metrics import binary_scores, latency_summary  # noqa: E402
from run_agent_eval import (  # noqa: E402
    DEFAULT_DATASET,
    DEFAULT_REPORT_DIR,
    _aggregate_llm_metrics,
    evaluate_components,
    evaluate_quality,
    load_dataset,
    save_report,
)
from run_local_kb_online import (  # noqa: E402
    DEFAULT_COMPLEX_QUERY_DATASET,
    DEFAULT_SIMPLE_DATASET,
    load_complex_cases,
    load_simple_cases,
    select_cases,
)


def _cohort_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    denominator = len(rows)
    ratio_fields = {
        "fact_threshold_pass": "fact_threshold_pass_rate",
        "citation_valid": "citation_valid_rate",
        "expected_document_retrieved": "expected_document_retrieved_rate",
        "reference_quality_pass": "reference_quality_pass_rate",
    }
    summary: dict[str, Any] = {
        "case_count": denominator,
        "latency": latency_summary(row["latency_ms"] for row in rows),
        "llm": _aggregate_llm_metrics(rows),
        "intent_accuracy": (
            sum(row.get("actual_intent") == row.get("expected_intent") for row in rows) / denominator
            if denominator and all(row.get("expected_intent") is not None for row in rows)
            else None
        ),
    }
    for field, output_field in ratio_fields.items():
        defined = [row[field] for row in rows if row.get(field) is not None]
        summary[output_field] = (
            sum(bool(value) for value in defined) / len(defined) if defined else None
        )
    return summary


def _stream_sample(
    agent: Any,
    case: dict[str, Any],
    *,
    retrieval_mode: str,
    is_first_message: bool,
) -> dict[str, Any]:
    from agent.schemas.chat import ChatRequest

    request = ChatRequest(
        query=case.get("online_query", case["query"]),
        session_id=f"latency-stream-{case['id']}-{uuid.uuid4().hex[:10]}",
        is_first_message=is_first_message,
        retrieval_mode=retrieval_mode,
    )
    started = time.perf_counter()
    first_event_ms: float | None = None
    first_token_ms: float | None = None
    done_ms: float | None = None
    chunks: list[str] = []
    status = ""
    for event_name, payload in agent.stream_chat(request):
        elapsed = (time.perf_counter() - started) * 1000
        if first_event_ms is None:
            first_event_ms = elapsed
        if event_name == "token":
            if first_token_ms is None:
                first_token_ms = elapsed
            if isinstance(payload, dict) and isinstance(payload.get("content"), str):
                chunks.append(payload["content"])
        elif event_name == "done":
            done_ms = elapsed
            if isinstance(payload, dict):
                status = str(payload.get("status", ""))

    result = agent.last_run_result
    metrics = result.llm_metrics if result is not None else {}
    title_stage = (metrics.get("by_stage") or {}).get("title_generation", {})
    return {
        "id": case["id"],
        "first_event_ms": round(first_event_ms, 2) if first_event_ms is not None else None,
        "first_token_ms": round(first_token_ms, 2) if first_token_ms is not None else None,
        "done_ms": round(done_ms, 2) if done_ms is not None else None,
        "status": status,
        "answer_length": len("".join(chunks)),
        "title_generation_calls": int(title_stage.get("call_count", 0)),
        "title_generation_ms": float(title_stage.get("total_ms", 0.0)),
        "llm_metrics": metrics,
    }


def _stream_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        field: latency_summary(
            row[field] for row in rows if row.get(field) is not None
        )
        for field in ("first_event_ms", "first_token_ms", "done_ms")
    }


def _retrieval_latency_scope(retrieval_mode: str) -> str:
    return "configured_hybrid" if retrieval_mode == "hybrid" else "controlled_non_hybrid"


def _component_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compound_rows = [row for row in rows if row.get("expected_parallel_target_count") is not None]
    clarification = binary_scores(
        [bool(row["expected_clarification"]) for row in rows],
        [bool(row["actual_clarification"]) for row in rows],
    ) if rows else {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "accuracy": 0.0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 0,
    }
    return {
        "case_count": len(rows),
        "latency": latency_summary(row["query_understanding_ms"] for row in rows),
        "llm": _aggregate_llm_metrics(rows),
        "intent_accuracy": (
            sum(row["intent_correct"] for row in rows) / len(rows) if rows else None
        ),
        "clarification": clarification,
        "mean_rewrite_term_recall": (
            sum(row["rewrite_term_recall"] for row in rows) / len(rows) if rows else None
        ),
        "compound_plan_accuracy": (
            sum(row["sub_query_count_correct"] for row in compound_rows) / len(compound_rows)
            if compound_rows else None
        ),
        "query_preparation_fallback_rate": (
            sum(bool(row["query_preparation_fallback"]) for row in rows) / len(rows)
            if rows else None
        ),
    }


def run_paired_ab(
    simple_cases: list[dict[str, Any]],
    complex_cases: list[dict[str, Any]],
    component_cases: list[dict[str, Any]],
    *,
    repeats: int,
    retrieval_mode: str = "bm25",
    measure_stream: bool = True,
    measure_first_message: bool = True,
) -> dict[str, Any]:
    from agent.agent import Agent

    if retrieval_mode not in {"hybrid", "vector", "bm25"}:
        raise ValueError("retrieval_mode must be hybrid, vector, or bm25")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    agents = {"baseline": Agent(), "cascaded": Agent()}
    agents["baseline"].query_understanding.cascaded_enabled = False
    agents["cascaded"].query_understanding.cascaded_enabled = True

    for agent in agents.values():
        search_tool = agent.registry.get_tool("search_documents")
        if search_tool is not None and hasattr(search_tool, "search"):
            search_tool.search("financial report", top_k=1, mode=retrieval_mode)

    cohorts = {"simple": simple_cases, "complex": complex_cases}
    quality_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        arm: {name: [] for name in cohorts} for arm in agents
    }
    paired: dict[str, list[dict[str, Any]]] = defaultdict(list)
    component_rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in agents}
    paired_components: list[dict[str, Any]] = []

    for repeat in range(repeats):
        for cohort_name, cases in cohorts.items():
            for case_index, case in enumerate(cases):
                arms = ["baseline", "cascaded"]
                if (repeat + case_index) % 2:
                    arms.reverse()
                samples: dict[str, dict[str, Any]] = {}
                for arm in arms:
                    measured = evaluate_quality(
                        [case],
                        repeats=1,
                        use_judge=False,
                        warmup_retrieval=False,
                        retrieval_mode=retrieval_mode,
                        agent=agents[arm],
                    )
                    row = dict(measured["cases"][0])
                    row["repeat"] = repeat + 1
                    row["arm"] = arm
                    row["cohort"] = cohort_name
                    quality_rows[arm][cohort_name].append(row)
                    samples[arm] = row
                paired[cohort_name].append({
                    "id": case["id"],
                    "repeat": repeat + 1,
                    "baseline_ms": samples["baseline"]["latency_ms"],
                    "cascaded_ms": samples["cascaded"]["latency_ms"],
                    "delta_ms": round(
                        samples["cascaded"]["latency_ms"]
                        - samples["baseline"]["latency_ms"],
                        2,
                    ),
                })

    for repeat in range(repeats):
        for case_index, case in enumerate(component_cases):
            arms = ["baseline", "cascaded"]
            if (repeat + case_index) % 2:
                arms.reverse()
            samples: dict[str, dict[str, Any]] = {}
            for arm in arms:
                measured = evaluate_components([case], agent=agents[arm])
                row = dict(measured["cases"][0])
                row["repeat"] = repeat + 1
                row["arm"] = arm
                component_rows[arm].append(row)
                samples[arm] = row
            paired_components.append({
                "id": case["id"],
                "repeat": repeat + 1,
                "baseline_ms": samples["baseline"]["query_understanding_ms"],
                "cascaded_ms": samples["cascaded"]["query_understanding_ms"],
                "delta_ms": round(
                    samples["cascaded"]["query_understanding_ms"]
                    - samples["baseline"]["query_understanding_ms"],
                    2,
                ),
            })

    stream_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        arm: {name: [] for name in cohorts} for arm in agents
    }
    if measure_stream:
        for repeat in range(repeats):
            for cohort_name, cases in cohorts.items():
                for case_index, case in enumerate(cases):
                    arms = ["baseline", "cascaded"]
                    if (repeat + case_index) % 2:
                        arms.reverse()
                    for arm in arms:
                        stream_rows[arm][cohort_name].append(
                            _stream_sample(
                                agents[arm],
                                case,
                                retrieval_mode=retrieval_mode,
                                is_first_message=False,
                            )
                        )

    first_message_rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in agents}
    if measure_first_message and simple_cases:
        for arm in ("baseline", "cascaded"):
            first_message_rows[arm].append(
                _stream_sample(
                    agents[arm],
                    simple_cases[0],
                    retrieval_mode=retrieval_mode,
                    is_first_message=True,
                )
            )

    return {
        "metadata": {
            "created_at": datetime.now().astimezone().isoformat(),
            "retrieval_mode": retrieval_mode,
            "retrieval_latency_scope": _retrieval_latency_scope(retrieval_mode),
            "retrieval_environment_equivalence_asserted": False,
            "repeats": repeats,
            "simple_case_ids": [case["id"] for case in simple_cases],
            "complex_case_ids": [case["id"] for case in complex_cases],
            "component_case_ids": [case["id"] for case in component_cases],
            "arm_order": "paired alternating by repeat and case",
            "judge_enabled": False,
        },
        "arms": {
            arm: {
                cohort_name: {
                    "summary": _cohort_summary(quality_rows[arm][cohort_name]),
                    "cases": quality_rows[arm][cohort_name],
                }
                for cohort_name in cohorts
            }
            for arm in agents
        },
        "paired_latency": {
            cohort_name: {
                "pairs": pairs,
                "delta": latency_summary(row["delta_ms"] for row in pairs),
            }
            for cohort_name, pairs in paired.items()
        },
        "component_arms": {
            arm: {"summary": _component_summary(rows), "cases": rows}
            for arm, rows in component_rows.items()
        },
        "paired_component_latency": {
            "pairs": paired_components,
            "delta": latency_summary(row["delta_ms"] for row in paired_components),
        },
        "stream_latency": {
            arm: {
                cohort_name: _stream_summary(rows)
                for cohort_name, rows in stream_rows[arm].items()
            }
            for arm in agents
        },
        "first_message_title_latency": {
            arm: _stream_summary(rows) | {
                "title_generation_calls": sum(row["title_generation_calls"] for row in rows),
                "title_generation_ms": round(sum(row["title_generation_ms"] for row in rows), 2),
            }
            for arm, rows in first_message_rows.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Paired Agent latency A/B for legacy and cascaded query understanding"
    )
    parser.add_argument("--online", action="store_true", help="confirm real model/API usage")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--simple-dataset", type=Path, default=DEFAULT_SIMPLE_DATASET)
    parser.add_argument("--complex-query-dataset", type=Path, default=DEFAULT_COMPLEX_QUERY_DATASET)
    parser.add_argument("--simple-limit", type=int, help="limit simple cases")
    parser.add_argument("--complex-limit", type=int, default=4, help="complex cases to include")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--retrieval-mode", choices=("hybrid", "vector", "bm25"), default="bm25")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.online:
        raise SystemExit("This evaluation invokes the configured model. Re-run with --online to confirm API usage.")
    if args.repeats < 3:
        raise SystemExit("paired latency evaluation requires at least 3 repeats")
    if args.complex_limit < 4:
        raise SystemExit("paired latency evaluation requires at least 4 complex cases")

    simple_cases = select_cases(load_simple_cases(args.simple_dataset), None, args.simple_limit)
    complex_cases = select_cases(
        load_complex_cases(args.dataset, args.complex_query_dataset),
        None,
        args.complex_limit,
    )
    component_cases = load_dataset(args.dataset)["component_cases"]
    report = run_paired_ab(
        simple_cases,
        complex_cases,
        component_cases,
        repeats=args.repeats,
        retrieval_mode=args.retrieval_mode,
    )
    report["metadata"]["dataset"] = str(args.dataset)
    output = args.output or DEFAULT_REPORT_DIR / f"agent_latency_ab_{datetime.now():%Y%m%d_%H%M%S}.json"
    save_report(report, output)
    print(json.dumps({
        "report": str(output),
        "retrieval_mode": args.retrieval_mode,
        "arms": {
            arm: {
                cohort: result["summary"]
                for cohort, result in cohorts.items()
            }
            for arm, cohorts in report["arms"].items()
        },
        "paired_delta": {
            cohort: result["delta"] for cohort, result in report["paired_latency"].items()
        },
        "component_arms": {
            arm: result["summary"] for arm, result in report["component_arms"].items()
        },
        "paired_component_delta": report["paired_component_latency"]["delta"],
        "stream_latency": report["stream_latency"],
        "first_message_title_latency": report["first_message_title_latency"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
