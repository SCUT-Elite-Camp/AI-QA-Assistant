"""Apply the frozen model-judge prompt to converted six-layer records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
AGENT_ROOT = PROJECT_ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agent.llm.llm_client import LLMClient
from agent.config.settings import settings


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("judge response must be an object")
    normalized_value: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
        normalized_value[normalized_key] = item
    value = normalized_value
    integer_fields = (
        "correctness", "completeness", "faithfulness", "answer_relevance",
        "limitation_disclosure", "conflict_handling",
    )
    # Kimi returns each dimension as {score, rationale/justification} even
    # when the prompt requests flat integers. Normalize that valid variant.
    dimension_rationales: list[str] = []
    for key in integer_fields:
        nested = value.get(key)
        if isinstance(nested, dict):
            value[key] = nested.get("score")
            explanation = nested.get("rationale") or nested.get("justification")
            if explanation:
                dimension_rationales.append(f"{key}: {explanation}")
    # judge_version identifies this runner-owned rubric, not a model score.
    # Some OpenAI-compatible models omit the constant field despite returning
    # every scored field; restoring this fixed metadata does not alter judgment.
    if value.get("judge_version") is None:
        value["judge_version"] = "judge.v1"
    if value.get("required_fact_ids_supported") is None:
        value["required_fact_ids_supported"] = []
    if value.get("unsupported_claim_ids") is None:
        # Never allow a low-faithfulness response that omitted claim IDs to
        # pass the deterministic unsupported-claim gate.
        value["unsupported_claim_ids"] = (
            [] if value.get("faithfulness") == 5
            else ["judge-unspecified-unsupported-claim"]
        )
    if value.get("rationale") is None:
        value["rationale"] = "\n".join(dimension_rationales) or (
            "The model returned dimension scores without a textual rationale."
        )
    if value.get("judge_version") != "judge.v1":
        raise ValueError(f"invalid judge_version:{value.get('judge_version')!r}")
    if any(not isinstance(value.get(key), int) or not 1 <= value[key] <= 5 for key in integer_fields):
        raise ValueError("judge scores must be integers from 1 to 5")
    for key in ("required_fact_ids_supported", "unsupported_claim_ids"):
        if not isinstance(value.get(key), list):
            raise ValueError(f"{key} must be a list; returned_keys={sorted(value)}")
    if not isinstance(value.get("rationale"), str):
        raise ValueError("rationale must be a string")
    return value


def judge_record(record: dict[str, Any], case: dict[str, Any], prompt: str, client: LLMClient) -> dict[str, Any]:
    if not str(record.get("report", {}).get("text") or "").strip():
        record["model_judge"] = {
            "judge_version": "judge.v1",
            "correctness": 1, "completeness": 1, "faithfulness": 1,
            "answer_relevance": 1, "limitation_disclosure": 1,
            "conflict_handling": 1, "required_fact_ids_supported": [],
            "unsupported_claim_ids": [],
            "rationale": "The candidate produced no report to evaluate.",
        }
        return record
    envelope = {
        "question": case["question"],
        "expected_behavior": case["expected_behavior"],
        "required_facts": [
            {"fact_id": item["fact_id"], "description": item["description"]}
            for item in case.get("required_facts", [])
        ],
        "frozen_excerpts": record.get("verified_evidence", []),
        "claims": record.get("claims", []),
        "candidate_report": record.get("report", {}).get("text", ""),
    }
    raw = client.generate(prompt + "\n\n" + json.dumps(envelope, ensure_ascii=False))
    try:
        record["model_judge"] = parse_json(raw)
    except ValueError as exc:
        raise ValueError(f"{exc}; raw={raw[:2000]!r}") from exc
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    dataset = {item["case_id"]: item for item in load(HERE / "datasets" / "cases.v1.json")["cases"]}
    prompt = (HERE / "prompts" / "model_judge.v1.md").read_text(encoding="utf-8")
    client = LLMClient()
    settings.LLM_TIMEOUT = args.timeout
    failures = 0
    count = 0
    for path in sorted(args.records.rglob("*.json")):
        record = load(path)
        if record.get("schema_version") != "1.0" or record.get("case_id") not in dataset:
            continue
        relative = path.relative_to(args.records)
        last_error: Exception | None = None
        for _ in range(args.retries + 1):
            try:
                judge_record(record, dataset[record["case_id"]], prompt, client)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            failures += 1
            record["judge_error"] = {"type": type(last_error).__name__, "message": str(last_error)}
        dump(args.output_dir / relative, record)
        count += 1
        print(f"[{'FAIL' if last_error else 'PASS'}] {record['run_id']}")
    print(f"judged {count} records; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
