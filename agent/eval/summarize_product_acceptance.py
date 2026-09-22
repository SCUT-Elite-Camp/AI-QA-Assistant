"""Compare product acceptance runs without re-running or changing judgments."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median


def records(directory: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((directory / "runs").glob("*.json"))]


def failure_hint(record: dict) -> str:
    if record.get("accepted"):
        return "pass"
    if "error" in record:
        return "evaluation_or_transport_error"
    if not record.get("runtime_ok"):
        return "runtime_or_route_failure"
    metrics = record.get("source_metrics", {})
    if metrics.get("out_of_scope_count", 0) or metrics.get("locator_excerpt_valid_rate") not in (None, 1.0):
        return "evidence_integrity_failure"
    if metrics.get("key_location_recall", 0) < 1:
        return "suspected_evidence_coverage_gap"
    return "answer_or_citation_quality_gap"


def summarize(rows: list[dict]) -> dict:
    result = {}
    for group in sorted({r["group"] for r in rows}):
        runs = [r for r in rows if r["group"] == group]
        result[group] = {
            "runs": len(runs), "accepted": sum(bool(r.get("accepted")) for r in runs),
            "runtime_ok": sum(bool(r.get("runtime_ok")) for r in runs),
            "failure_hints": dict(Counter(failure_hint(r) for r in runs)),
            "median_response_seconds": median([r["latency_seconds"] for r in runs if "latency_seconds" in r]) if any("latency_seconds" in r for r in runs) else None,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before, after = records(args.before), records(args.after)
    if not before or not after:
        parser.error("both directories must contain run records")
    if any("accepted" not in r for r in before + after):
        parser.error("run still in progress: missing final judgment")
    summary = {"before": summarize(before), "after": summarize(after)}
    lines = ["# Agent 真实问题验收对照", "", "自动裁判结果，待人工复核；不是 dev 全项目验收。不同代码版本的重复次数分别列出，不混合计数。", "",
             "| 用例 | G1 修复前 | G1 修复后 | G2 修复前 | G2 修复后 |", "|---|---:|---:|---:|---:|"]
    for case in sorted({r["case_id"] for r in before + after}):
        values = []
        for group in ("G1", "G2"):
            for rows in (before, after):
                subset = [r for r in rows if r["case_id"] == case and r["group"] == group]
                values.append(f"{sum(bool(r.get('accepted')) for r in subset)}/{len(subset)}")
        lines.append("| " + " | ".join([case] + values) + " |")
    lines += ["", "## 修复后失败记录", "", "以下归因是定位提示，不是确定根因；相邻 chunk 也可能包含正确答案，应结合原文核验。", ""]
    for r in after:
        if r.get("accepted"):
            continue
        lines.extend([f"### {r['case_id']} / {r['group']} / r{r['repeat']}", "",
                      f"定位提示：{failure_hint(r)}。", "",
                      r.get("error") or (r.get("judge") or {}).get("rationale", "缺少裁判说明"), ""])
    if all(r.get("accepted") for r in after):
        lines += ["本次自动判定没有失败项；不代表未覆盖场景也通过。", ""]
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
