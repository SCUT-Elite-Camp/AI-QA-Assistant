"""Build the effective G1/G2 result set and apply Codex offline review.

This script makes no network or LLM calls.  Judgments are a frozen manual
review of the 2026-09-21/22 formal runs against cases.v1.json.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "eval/deep_research_a/datasets/cases.v1.json"
RUNS = ROOT / "agent/outputs/deep_research_benchmark"
OUT = ROOT / "eval/reports/g1-g2-0922-codex-offline-judge"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def envelopes(directory: str, group: str):
    found = {}
    for path in (RUNS / directory).rglob("*.json"):
        try:
            item = load(path)
        except (OSError, json.JSONDecodeError):
            continue
        if item.get("schema_version") != "deep-research-run.v1" or item.get("group") != group:
            continue
        found[(item["case_id"], int(item["repetition"]))] = (item, path)
    return found


def answer(item):
    result = item.get("result") or {}
    if item["group"] == "fast_chat":
        return str((result.get("response") or {}).get("answer") or "")
    return str((result.get("report") or {}).get("markdown") or "")


# Scores: correctness, completeness, faithfulness, relevance,
# limitation disclosure, conflict handling.  4 is the acceptance threshold.
G1 = {
    1:(4,3,5,5,3,3), 2:(5,5,5,5,4,3), 3:(5,5,5,5,4,3),
    4:(4,4,5,5,4,3), 5:(3,2,5,4,4,2), 6:(3,2,5,4,3,2),
    7:(5,5,5,5,5,3), 8:(2,1,4,2,4,3), 9:(5,5,5,5,4,3),
    10:(5,5,5,5,4,3), 11:(5,5,5,5,4,3), 12:(1,1,3,1,1,3),
    13:(5,5,5,5,4,3), 14:(5,5,5,5,4,3), 15:(5,5,5,5,5,3),
    16:(5,5,5,5,5,3), 17:(5,5,5,5,4,3), 18:(1,1,3,1,1,3),
}
G2 = {
    1:(4,3,5,2,2,3), 2:(4,3,5,2,2,3), 3:(5,4,5,2,2,3),
    4:(4,2,5,2,2,2), 5:(3,2,4,2,3,1), 6:(3,2,5,2,2,2),
    7:(2,1,5,1,1,3), 8:(2,1,4,2,3,3), 9:(4,3,5,2,2,3),
    10:(3,2,5,2,2,3), 11:(4,3,5,2,2,3), 12:(1,1,4,2,4,3),
    13:(3,2,5,2,2,3), 14:(2,1,4,1,2,3), 15:(4,3,5,2,1,3),
    16:(2,1,5,1,1,3), 17:(4,4,5,2,2,1), 18:(1,1,4,2,4,2),
}


REASONS_G1 = {
    1:"给出 W30 和 W34 总数，但缺 W34 分类计数及四项差值。",
    4:"长期归档、/agent 和 49 正确，但 00 层目录名称未完整给出。",
    5:"只覆盖七月依赖，未形成七月至九月的演进及九月遗留限制。",
    6:"只引用优化说明，未核实 Goals 中 AG-M8 的 Not started/Wk03 状态。",
    8:"没有按题意澄清“最新架构”的口径。",
    12:"未检索到相关上下文，未回答里程碑状态。",
    18:"未检索到相关上下文，未完成九月验收态势综合。",
}
REASONS_G2 = {
    1:"堆叠两周原始材料，未计算四项变化。",
    2:"材料包含核心数字，但未清楚汇总且未解释模块数不可直接相加。",
    3:"原始证据包含提交与文件，但没有整理为对应关系。",
    4:"主要输出 Agent 归档，未完整回答三层目录职责；还存在误报冲突。",
    5:"读取了两期材料，但未完整指出 hard-coded 与 broken evidence links，并误报冲突。",
    6:"未明确给出 AG-M8 Not started 与 Wk03，仅堆叠来源。",
    7:"没有拒绝 99.9% SLA 结论，仅返回无关的周报材料。",
    8:"没有发起必要澄清。",
    9:"包含周报数字但没有完成 +5/+9/+14 计算。",
    10:"没有明确完成 5+1=6、1<=1 及通过判定。",
    11:"包含模块表，但未解释模块行与项目总数不可相加。",
    12:"以资料不足结束，未给出 M6-M11 的状态区分。",
    13:"没有形成直接回答，且引用定位未达到冻结集要求的关键 chunk。",
    14:"检索被无关 W28/W30 Master 材料干扰，未回答作者、日期与周提交数。",
    15:"包含 W33 数字，但未明确权限/时间范围限制。",
    16:"没有按要求拒绝推断 W34 Web 精确数字。",
    17:"事实大体齐全，但以原始材料堆叠呈现，并把两个模块的不同数值误判为冲突。",
    18:"以资料不足结束，未综合九月演示状态、限制与 Goals 进度。",
}


def main():
    cases = {c["case_id"]: c for c in load(CASES_PATH)["cases"]}
    g1 = envelopes("g1-a95b-formal-18x3-0922", "fast_chat")
    # Replace transient failures with successful targeted retries.
    retry5 = envelopes("g1-a95b-transient-retry-0922-dr005", "fast_chat")
    retry_final = envelopes("g1-a95b-transient-retry-0922-final", "fast_chat")
    retry_last = envelopes("g1-a95b-transient-retry-0922-last", "fast_chat")
    g1[("DR-A-005",1)] = retry5[("DR-A-005",1)]
    g1[("DR-A-005",2)] = retry5[("DR-A-005",2)]
    g1[("DR-A-005",3)] = retry_last[("DR-A-005",1)]
    g1[("DR-A-006",2)] = retry_final[("DR-A-006",1)]

    g2 = envelopes("g2-formal-18x3-0921", "deep_research_current")
    retry2 = envelopes("g2-formal-failed-retry-0922", "deep_research_current")
    g2[("DR-A-001",3)] = retry2[("DR-A-001",1)]
    g2[("DR-A-002",2)] = retry2[("DR-A-002",1)]
    g2[("DR-A-008",2)] = retry2[("DR-A-008",1)]

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, runs, rubric in (("G1", g1, G1), ("G2", g2, G2)):
        for number in range(1, 19):
            case_id = f"DR-A-{number:03d}"
            for repeat in range(1, 4):
                item, path = runs[(case_id, repeat)]
                scores = list(rubric[number])
                # G1 case 15 had one successful answer and two genuine no-context results.
                if label == "G1" and number == 15 and repeat in (2, 3):
                    scores = [1,1,3,1,1,3]
                text = answer(item)
                terminal_ok = bool(text.strip()) and not item.get("error")
                accepted = terminal_ok and min(scores[:4]) >= 4
                reason = (REASONS_G1 if label == "G1" else REASONS_G2).get(
                    number, "完整覆盖冻结事实，结论直接且有来源支撑。"
                )
                if not terminal_ok:
                    reason = "运行未产生可评估答案。" if item.get("error") else reason
                rows.append({
                    "group": label, "case_id": case_id, "repeat": repeat,
                    "category": cases[case_id]["category"],
                    "correctness": scores[0], "completeness": scores[1],
                    "faithfulness": scores[2], "answer_relevance": scores[3],
                    "limitation_disclosure": scores[4], "conflict_handling": scores[5],
                    "terminal_ok": terminal_ok, "accepted": accepted,
                    "reason": reason, "source_run": str(path.relative_to(ROOT)),
                    "judge_type": "codex_offline_review", "external_model_calls": 0,
                })

    with (OUT / "judgments.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (OUT / "judgments.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    summary = {}
    for group in ("G1", "G2"):
        subset = [r for r in rows if r["group"] == group]
        by_case = defaultdict(list)
        for row in subset: by_case[row["case_id"]].append(row)
        summary[group] = {
            "runs": len(subset),
            "terminal_ok": sum(r["terminal_ok"] for r in subset),
            "accepted": sum(r["accepted"] for r in subset),
            "acceptance_rate": round(sum(r["accepted"] for r in subset)/len(subset), 4),
            "mean_scores": {key: round(sum(r[key] for r in subset)/len(subset), 3) for key in (
                "correctness","completeness","faithfulness","answer_relevance",
                "limitation_disclosure","conflict_handling")},
            "case_stability": Counter(
                "3/3" if sum(r["accepted"] for r in values)==3 else
                "partial" if any(r["accepted"] for r in values) else "0/3"
                for values in by_case.values()
            ),
        }
    metadata = {
        "judge_type":"codex_offline_review", "external_model_calls":0,
        "dataset":"cp2-deep-research-cases.v1", "effective_runs":108,
        "acceptance_rule":"terminal_ok and correctness/completeness/faithfulness/answer_relevance >= 4",
        "summary":summary,
    }
    (OUT / "summary.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    lines = ["# G1/G2 Codex 离线复核评分", "", "本报告未调用外部评审模型；108 条结果由 Codex 对照冻结评测集逐条复核。", "",
             "## 判定规则", "", "正确性、完整性、忠实性、回答相关性均不低于 4 分，且有可评估答案，才计为通过。", ""]
    for group in ("G1","G2"):
        s=summary[group]
        lines += [f"## {group}", "", f"- 有效运行：{s['terminal_ok']} / {s['runs']}",
                  f"- 通过：{s['accepted']} / {s['runs']}（{s['acceptance_rate']:.1%}）",
                  f"- 稳定通过题：{s['case_stability'].get('3/3',0)} / 18",
                  f"- 部分通过题：{s['case_stability'].get('partial',0)} / 18",
                  f"- 0/3 通过题：{s['case_stability'].get('0/3',0)} / 18",
                  f"- 六维均分：{s['mean_scores']}", ""]
    lines += ["## 结论", "", "G1 在直接问答质量上明显优于当前 G2。G2 虽已完成 54/54 次运行，但大量结果是证据原文堆叠，缺少计算、归纳、拒答或澄清，因此不能把运行完成率当作效果通过率。", "",
              "逐条评分与理由见 `judgments.csv`；原始来源路径保留在 `source_run` 列。", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
