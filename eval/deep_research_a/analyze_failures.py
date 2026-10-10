"""Generate deterministic failure and hard-gate reports from scored runs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any


def _load_scores(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def analyze(scores: list[dict[str, Any]], *, retrieval_observability: str = "persisted") -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in scores:
        groups[str(score["group"])].append(score)
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "retrieval_observability": retrieval_observability,
        "groups": {},
    }
    for group, rows in sorted(groups.items()):
        root_causes = Counter(str(row.get("root_cause") or "PASS") for row in rows)
        failure_codes = Counter(code for row in rows for code in row.get("failure_codes", []))
        gate_failures = Counter(
            gate
            for row in rows
            for gate, outcome in row.get("hard_gates", {}).items()
            if outcome.get("passed") is False
        )
        failed_cases: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            for code in row.get("failure_codes", []):
                failed_cases[str(row["case_id"])].add(code)
        result["groups"][group] = {
            "run_count": len(rows),
            "hard_gate_pass_count": sum(bool(row.get("hard_gate_pass")) for row in rows),
            "root_causes": dict(root_causes.most_common()),
            "failure_codes": dict(failure_codes.most_common()),
            "hard_gate_failures": dict(gate_failures.most_common()),
            "failed_cases": {case: sorted(codes) for case, codes in sorted(failed_cases.items())},
        }
    return result


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# Deep Research 失败归因与硬门槛报告", "", "> Page Index（G3）属于外部工具/数据层依赖，不计入本报告的完成门槛。", ""]
    if report.get("retrieval_observability") == "legacy":
        lines.extend([
            "> 本报告基于补齐评测 Trace 接口前的历史运行结果；Retrieval/Evidence 根因仅为暂定结论，需用新链路定向复测后确认。",
            "",
        ])
    for group, item in report["groups"].items():
        lines.extend([
            f"## {group}", "",
            f"- 运行数：{item['run_count']}",
            f"- 硬门槛通过：{item['hard_gate_pass_count']} / {item['run_count']}", "",
            "### 根因分布", "",
        ])
        lines.extend(f"- `{name}`：{count}" for name, count in item["root_causes"].items())
        lines.extend(["", "### 硬门槛失败分布", ""])
        lines.extend(f"- `{name}`：{count}" for name, count in item["hard_gate_failures"].items())
        lines.extend(["", "### 失败用例", ""])
        lines.extend(f"- `{case}`：{', '.join(codes)}" for case, codes in item["failed_cases"].items())
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scores", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieval-observability", choices=("persisted", "legacy"), default="persisted")
    args = parser.parse_args()
    report = analyze(_load_scores(args.scores), retrieval_observability=args.retrieval_observability)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "failure_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "failure_analysis.md").write_text(_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
