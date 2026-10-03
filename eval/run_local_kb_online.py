"""Run local-knowledge-base online answer evaluation by complexity."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from run_agent_eval import (
    DEFAULT_DATASET,
    DEFAULT_REPORT_DIR,
    ROOT,
    evaluate_quality,
    load_dataset,
)

DEFAULT_SIMPLE_DATASET = Path(__file__).parent / "datasets" / "local_kb_simple_online_cases.json"
DEFAULT_COMPLEX_QUERY_DATASET = (
    Path(__file__).parent / "datasets" / "local_kb_complex_online_queries_en.json"
)


def load_simple_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("simple online dataset must contain a non-empty 'cases' list")
    ids = [case.get("id") for case in cases]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("simple online cases must have unique non-empty ids")
    return [{**case, "test_complexity": "simple"} for case in cases]


def load_complex_cases(
    path: Path,
    query_path: Path = DEFAULT_COMPLEX_QUERY_DATASET,
) -> list[dict[str, Any]]:
    dataset = load_dataset(path)
    quality_cases = [
        {**case, "test_complexity": "complex"}
        for case in dataset["quality_cases"]
    ]
    compound_cases = [
        {
            **case,
            "test_complexity": "complex",
            "min_citations": case.get("min_citations", 1),
        }
        for case in dataset["component_cases"]
        if case["id"].startswith("local_compound_")
    ]
    cases = quality_cases + compound_cases
    overlay = json.loads(query_path.read_text(encoding="utf-8")).get("queries")
    if not isinstance(overlay, dict):
        raise ValueError("complex English query dataset must contain a 'queries' object")
    case_ids = {case["id"] for case in cases}
    missing = sorted(case_ids - set(overlay))
    extra = sorted(set(overlay) - case_ids)
    if missing or extra:
        raise ValueError(
            f"complex English query IDs do not match the base dataset; missing={missing}, extra={extra}"
        )
    return [
        {**case, "query": overlay[case["id"]], "online_query": overlay[case["id"]]}
        for case in cases
    ]


def select_cases(
    cases: list[dict[str, Any]],
    case_ids: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        requested = set(case_ids)
        selected = [case for case in selected if case["id"] in requested]
    if limit is not None:
        selected = selected[:limit]
    return selected


def configure_retrieval_namespace(namespace: str | None) -> str:
    if not namespace:
        return "default"
    if not namespace.replace("_", "").isalnum():
        raise ValueError("retrieval namespace may contain only letters, digits, and underscores")
    namespace_dir = ROOT / "data-persistence" / "data" / "namespaces" / namespace
    os.environ["RETRIEVAL_COLLECTION"] = f"{namespace}_chunks"
    os.environ["RETRIEVAL_DOCUMENTS_DIR"] = str(namespace_dir / "documents")
    os.environ["RETRIEVAL_BM25_PATH"] = str(namespace_dir / "bm25_index.pkl")
    return namespace


def save_online_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for suite_name in ("simple", "complex"):
        rows = report.get(suite_name, {}).get("cases", [])
        if not rows:
            continue
        scalar_keys = [
            key for key, value in rows[0].items()
            if not isinstance(value, (dict, list))
        ]
        csv_path = output.with_name(f"{output.stem}_{suite_name}.csv")
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=scalar_keys)
            writer.writeheader()
            writer.writerows(
                {key: row.get(key) for key in scalar_keys}
                for row in rows
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Online local-KB evaluation split into simple and complex questions",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=("all", "simple", "ordinary", "complex"),
        default="all",
        help="ordinary is an alias of simple",
    )
    parser.add_argument("--online", action="store_true", help="confirm real model/API usage")
    parser.add_argument("--list", action="store_true", help="list selected cases without calling APIs")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--simple-dataset", type=Path, default=DEFAULT_SIMPLE_DATASET)
    parser.add_argument(
        "--complex-query-dataset",
        type=Path,
        default=DEFAULT_COMPLEX_QUERY_DATASET,
    )
    parser.add_argument("--case-id", action="append", help="run only this case; may be repeated")
    parser.add_argument("--limit", type=int, help="run the first N selected cases in each class")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--judge", action="store_true", help="add relevance and faithfulness judge calls")
    parser.add_argument("--no-retrieval-warmup", action="store_true")
    parser.add_argument("--retrieval-namespace")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    mode = "simple" if args.mode == "ordinary" else args.mode
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    simple_cases = select_cases(
        load_simple_cases(args.simple_dataset), args.case_id, args.limit
    )
    complex_cases = select_cases(
        load_complex_cases(args.dataset, args.complex_query_dataset),
        args.case_id,
        args.limit,
    )
    selected = {
        name: cases
        for name, cases in (("simple", simple_cases), ("complex", complex_cases))
        if mode in ("all", name) and cases
    }
    if not selected:
        raise SystemExit("no cases matched the requested mode and case ids")

    if args.list:
        print(json.dumps(
            {name: [case["id"] for case in cases] for name, cases in selected.items()},
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if not args.online:
        raise SystemExit(
            "This test calls configured online models. Re-run with --online to confirm API usage."
        )

    try:
        namespace = configure_retrieval_namespace(args.retrieval_namespace)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    report: dict[str, Any] = {
        "metadata": {
            "created_at": datetime.now().astimezone().isoformat(),
            "mode": mode,
            "dataset": str(args.dataset),
            "simple_dataset": str(args.simple_dataset),
            "complex_query_dataset": str(args.complex_query_dataset),
            "model": os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME") or "configured-default",
            "fast_answer_model": os.getenv("FAST_ANSWER_MODEL") or "configured-default",
            "query_preparation_model": os.getenv("QUERY_PREPARATION_MODEL") or "configured-default",
            "judge_enabled": args.judge,
            "repeats": args.repeats,
            "retrieval_namespace": namespace,
        }
    }
    for name, cases in selected.items():
        report[name] = evaluate_quality(
            cases,
            repeats=args.repeats,
            use_judge=args.judge,
            warmup_retrieval=not args.no_retrieval_warmup,
        )

    output = args.output or DEFAULT_REPORT_DIR / (
        f"local_kb_online_{mode}_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    save_online_report(report, output)
    print(json.dumps({
        "report": str(output),
        "summary": {
            name: values["summary"]
            for name, values in report.items()
            if name != "metadata"
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
