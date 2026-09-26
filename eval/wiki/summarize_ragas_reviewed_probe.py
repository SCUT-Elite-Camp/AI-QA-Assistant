"""Validate and summarize a complete paired Wiki Ragas PROBE run."""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from pathlib import Path


ARMS = ("P0_DIRECT", "P1_WIKI_GUIDED")
METRICS = (
    "ragas_context_precision", "ragas_context_recall", "answer_correctness",
    "faithfulness", "unsupported_claim_rate", "ragas_id_context_precision",
    "ragas_id_context_recall",
)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _by_id(rows: list[dict], name: str) -> dict[str, dict]:
    result = {row[name]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate {name}")
    return result


def _interval(deltas: list[float], *, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(
        sum(deltas[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(10_000)
    )
    return means[249], means[9749]


def summarize(directory: Path) -> dict:
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    queries = json.loads((directory / "queries.json").read_text(encoding="utf-8"))
    traces = _by_id(_load_jsonl(directory / "traces.jsonl"), "record_id")
    scores = _by_id(_load_jsonl(directory / "scores.jsonl"), "record_id")
    query_ids = [row["query_id"] for row in queries]
    expected = {f"{query_id}:{arm}" for query_id in query_ids for arm in ARMS}
    if len(query_ids) != len(set(query_ids)) or len(query_ids) != report["query_count"]:
        raise ValueError("query cohort is incomplete or duplicated")
    if set(traces) != expected or set(scores) != expected:
        raise ValueError("both retrieval paths must cover every cohort query")
    if report["errors"] or not report["probe_run_complete"]:
        raise ValueError("PROBE report is incomplete")
    if report["gate_d"] != "NOT_RUN" or report["status"] != "PARTIAL":
        raise ValueError("PROBE must preserve Gate D and release status")
    if any(row.get("error") for row in [*traces.values(), *scores.values()]):
        raise ValueError("a trace or score has an error")

    paired = {}
    for metric in METRICS:
        direct = []
        guided = []
        for query_id in query_ids:
            values = [scores[f"{query_id}:{arm}"]["metrics"][metric] for arm in ARMS]
            if any(not isinstance(value, (float, int)) or not 0 <= value <= 1 for value in values):
                raise ValueError(f"invalid {metric} value for {query_id}")
            direct.append(float(values[0]))
            guided.append(float(values[1]))
        deltas = [right - left for left, right in zip(direct, guided, strict=True)]
        low, high = _interval(deltas, seed=20260918)
        paired[metric] = {
            "p0_mean": round(statistics.mean(direct), 4),
            "p1_mean": round(statistics.mean(guided), 4),
            "p1_minus_p0": round(statistics.mean(deltas), 4),
            "paired_bootstrap_ci95": [round(low, 4), round(high, 4)],
            "p1_higher": sum(delta > 1e-9 for delta in deltas),
            "p1_lower": sum(delta < -1e-9 for delta in deltas),
            "ties": sum(abs(delta) <= 1e-9 for delta in deltas),
        }

    unusual_citation_style = []
    for record_id, row in traces.items():
        citations = re.findall(r"\[E(\d+)\]", row["answer"])
        if not citations or any(int(number) > report["answer_context_cutoff"] for number in citations):
            unusual_citation_style.append(record_id)

    return {
        "status": "PARTIAL", "probe_run_complete": True, "gate_d": "NOT_RUN",
        "query_count": len(query_ids), "paired_records": len(scores), "score_errors": 0,
        "paired_metrics": paired,
        "answer_citation_format_review": {
            "unusual_count": len(unusual_citation_style),
            "record_ids": sorted(unusual_citation_style),
            "note": "Format check only; a list or range of valid E numbers is flagged.",
        },
        "latency_note": (
            "Raw retrieval_seconds are not comparable: P0 query vectors were precomputed, "
            "while P1 timed its BGE-M3 query encoding. Production Milvus latency was not tested."
        ),
        "interpretation_limits": report["limits"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = summarize(args.directory)
    output = args.directory / "paired-analysis.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
