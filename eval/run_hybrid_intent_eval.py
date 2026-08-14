import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "agent"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent.query import (
    HybridIntentRouter,
    IntentResult,
    QueryIntent,
    SentenceTransformerIntentEncoder,
)


class RecordingFallback:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, query: str, history: list[dict]) -> IntentResult:
        self.calls += 1
        return IntentResult(
            intent=QueryIntent.KNOWLEDGE_QA,
            confidence=0.0,
            reason="llm_fallback_required",
        )


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile_value
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.72)
    parser.add_argument("--margin", type=float, default=0.08)
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    fallback = RecordingFallback()
    router = HybridIntentRouter(
        fallback=fallback,  # type: ignore[arg-type]
        encoder=SentenceTransformerIntentEncoder(args.model_path),
        enabled=True,
        threshold=args.threshold,
        margin=args.margin,
    )
    warmup_started = time.perf_counter()
    router.warmup()
    warmup_ms = (time.perf_counter() - warmup_started) * 1000

    rows = []
    for case in dataset["component_cases"]:
        started = time.perf_counter()
        result = router.classify(case["query"], case.get("history") or [])
        latency_ms = (time.perf_counter() - started) * 1000
        fallback_required = result.reason == "llm_fallback_required"
        if result.reason == "high_precision_rule":
            source = "rule"
        elif result.reason.startswith("embedding"):
            source = "embedding"
        else:
            source = "llm_fallback"
        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "expected_intent": case["expected_intent"],
                "predicted_intent": None if fallback_required else result.intent.value,
                "source": source,
                "fallback_required": fallback_required,
                "covered_correct": (
                    None
                    if fallback_required
                    else result.intent.value == case["expected_intent"]
                ),
                "confidence": result.confidence,
                "reason": result.reason,
                "latency_ms": round(latency_ms, 2),
            }
        )

    covered = [row for row in rows if not row["fallback_required"]]
    correct = [row for row in covered if row["covered_correct"]]
    latencies = [row["latency_ms"] for row in rows]
    summary = {
        "case_count": len(rows),
        "rule_count": sum(row["source"] == "rule" for row in rows),
        "embedding_count": sum(row["source"] == "embedding" for row in rows),
        "llm_fallback_count": sum(row["source"] == "llm_fallback" for row in rows),
        "local_coverage": len(covered) / len(rows),
        "covered_accuracy": len(correct) / len(covered) if covered else 0.0,
        "llm_fallback_rate": fallback.calls / len(rows),
        "warmup_ms": round(warmup_ms, 2),
        "mean_local_routing_ms": round(statistics.mean(latencies), 2),
        "p50_local_routing_ms": round(percentile(latencies, 0.5), 2),
        "p95_local_routing_ms": round(percentile(latencies, 0.95), 2),
    }
    output = {
        "metadata": {
            "dataset": args.dataset,
            "model_path": args.model_path,
            "threshold": args.threshold,
            "margin": args.margin,
        },
        "summary": summary,
        "cases": rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
