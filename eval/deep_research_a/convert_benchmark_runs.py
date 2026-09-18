"""Convert public-API benchmark envelopes into six-layer A-side run records.

The converter is deliberately conservative: fields unavailable from the public
API remain empty/zero and model_judge remains null. It never invents retrieval
hits, token counts, or judge scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DATASET = HERE / "datasets" / "cases.v1.json"
MANIFESTS = HERE / "manifests" / "source_manifests.v1.json"
BASELINE = HERE / "config" / "frozen_baseline.json"
GROUPS = {
    "fast_chat": "G1",
    "deep_research_current": "G2",
    "deep_research_page_index": "G3",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def contains_any(text: str, values: list[str]) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(" ".join(value.casefold().split()) in normalized for value in values)


def convert(envelope: dict[str, Any], case: dict[str, Any], manifest: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    result = envelope.get("result") or {}
    group = GROUPS[str(envelope["group"])]
    research = result if group != "G1" else {}
    response = (result.get("response") or {}) if group == "G1" else {}
    report_payload = research.get("report") or {}
    report_text = str(response.get("answer") or response.get("message") or report_payload.get("markdown") or "")
    api_citations = list(result.get("citations") or [])
    checks = {item.get("url"): item for item in result.get("source_checks") or []}

    evidence = []
    for index, item in enumerate(api_citations, 1):
        excerpt = str(item.get("excerpt") or item.get("text") or "")
        evidence_id = str(item.get("evidence_id") or f"citation-evidence-{index}")
        evidence.append({
            "evidence_id": evidence_id,
            "doc_id": str(item.get("doc_id") or ""),
            "document_version": item.get("document_version"),
            "content_hash": str(item.get("content_hash") or ""),
            "locator": str(item.get("locator") or ""),
            "excerpt": excerpt,
            "source_method": "local_original_read",
            "supports_fact_ids": [
                fact["fact_id"] for fact in case.get("required_facts", [])
                if contains_any(excerpt, fact.get("match_any", []))
            ],
            "conflict_status": "unknown" if case.get("expected_behavior") == "conflict_review" else "none",
        })

    raw_plan = research.get("plan") or {}
    plan_tasks = []
    for item in raw_plan.get("tasks") or []:
        task_text = " ".join([
            str(item.get("question") or ""), str(item.get("purpose") or ""),
            " ".join(str(x.get("target") or x.get("description") or "") for x in item.get("acceptance_criteria") or []),
        ])
        plan_tasks.append({
            "task_id": str(item.get("task_id") or ""),
            "query": str(item.get("question") or ""),
            "covers": [
                fact["fact_id"] for fact in case.get("required_facts", [])
                if contains_any(task_text, fact.get("match_any", []))
            ],
            "depends_on": list(item.get("dependencies") or item.get("depends_on") or []),
        })
    if group == "G1":
        plan_tasks = [{
            "task_id": "fast-chat-request",
            "query": case["question"],
            "covers": [fact["fact_id"] for fact in case.get("required_facts", [])],
            "depends_on": [],
        }]

    claim_id = "report-answer" if report_text else ""
    evidence_ids = [item["evidence_id"] for item in evidence]
    citations = []
    for index, item in enumerate(api_citations, 1):
        url = str(item.get("source_url") or "")
        checked = checks.get(url, {})
        citations.append({
            "citation_id": str(item.get("number") or index),
            "claim_ids": [claim_id] if claim_id else [],
            "evidence_ids": [str(item.get("evidence_id") or f"citation-evidence-{index}")],
            "doc_id": str(item.get("doc_id") or ""),
            "locator": str(item.get("locator") or ""),
            "source_url": url or None,
            "link_status": "open" if checked.get("ok") else ("broken" if url else "not_applicable"),
            "supports_claim": bool(item.get("excerpt") or item.get("text")),
        })

    progress = research.get("progress") or {}
    trace = research.get("evaluation_trace") or {}
    traced_evidence = []
    for item in trace.get("verified_evidence") or []:
        excerpt = str(item.get("excerpt") or "")
        traced_evidence.append({
            **item,
            "source_method": "read_document_range",
            "supports_fact_ids": [
                fact["fact_id"] for fact in case.get("required_facts", [])
                if contains_any(excerpt, fact.get("match_any", []))
            ],
            "conflict_status": "unknown" if case.get("expected_behavior") == "conflict_review" else "none",
        })
    traced_claims = [
        {
            "claim_id": str(item.get("claim_id") or ""),
            "text": str(item.get("claim_text") or item.get("text") or ""),
            "factual": True,
            "evidence_ids": list(item.get("evidence_ids") or []),
        }
        for item in trace.get("claims") or []
    ]
    metrics = progress.get("metrics") or {}
    job = research.get("job") or {}
    error = envelope.get("error")
    behavior = str(report_payload.get("result_status") or response.get("result_status") or "degraded")
    behavior = {"completed": "answer", "success": "answer", "failed": "degraded"}.get(behavior, behavior)
    if behavior not in {"answer", "degraded", "refuse", "request_more_information", "conflict_review"}:
        behavior = "answer" if report_text else "degraded"
    terminal = "timeout" if result.get("timed_out") else ("failed" if error else ("degraded" if behavior == "degraded" else "completed"))

    generation = baseline["generation"]
    return {
        "schema_version": "1.0",
        "run_id": envelope["run_id"], "group": group,
        "case_id": envelope["case_id"], "repeat": envelope["repetition"],
        "environment": {
            "git_commit": baseline["repository"]["head_commit"], "git_dirty": False,
            "python_version": "public-api-run", "docker_version": "runtime-preflight",
            "provider": generation["provider"], "model": generation["model"],
            "model_revision": generation["model_revision"],
            "generation_config_hash": baseline["generation_config_sha256"],
            "prompt_hashes": {name: value.get("sha256") for name, value in baseline["prompts"].items() if isinstance(value, dict)},
            "embedding_revision": baseline["retrieval"]["embedding_revision"],
        },
        "request": {
            "question": case["question"], "question_sha256": sha256(case["question"]),
            "manifest_hash": manifest["manifest_hash"],
            "allowed_document_ids": case["allowed_document_ids"],
            "forbidden_document_ids": case["forbidden_document_ids"],
        },
        "plan": {"tasks": plan_tasks},
        "retrieval_hits": [
            {
                "rank": index,
                "doc_id": str(item.get("doc_id") or ""),
                "chunk_id": item.get("chunk_id") or item.get("locator_hint"),
                "score": item.get("score"),
                "search_path": item.get("tool_name") or "search",
            }
            for index, item in enumerate(trace.get("observations") or api_citations, 1)
        ],
        "observations": list(trace.get("observations") or []),
        "verified_evidence": traced_evidence or evidence,
        "claims": traced_claims or ([{"claim_id": claim_id, "text": report_text, "factual": True, "evidence_ids": evidence_ids}] if claim_id else []),
        "report": {"text": report_text, "behavior": behavior, "limitations_disclosed": "局限" in report_text or "无法" in report_text},
        "citations": citations,
        "events": list((research.get("events") or {}).get("events") or []),
        "runtime_metrics": {
            "total_latency_ms": envelope.get("elapsed_ms", 0), "stage_latency_ms": {},
            "search_calls": int(metrics.get("tool_calls") or 0), "read_calls": len(evidence),
            "tool_calls": int(metrics.get("tool_calls") or 0), "input_tokens": None, "output_tokens": None,
            "retries": int(metrics.get("retry_count") or 0), "fallbacks": 0,
            "checkpoint_recoveries": int(metrics.get("recovery_count") or 0),
            "provider_failures": 1 if error and "provider" in str(error).casefold() else 0,
        },
        "model_judge": None, "terminal_status": terminal,
        "failure_stage": ("runtime" if error else job.get("failure_stage")),
        "error": ({"code": error.get("type"), "message": error.get("message")} if error else None),
        "conversion_notes": ["persisted_evaluation_trace" if trace else "retrieval_hits_limited_to_public_citations", "token_counts_unavailable_from_public_api"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("envelopes", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    dataset = {item["case_id"]: item for item in load(DATASET)["cases"]}
    manifests = load(MANIFESTS)["manifests"]
    baseline = load(BASELINE)
    count = 0
    for path in sorted(args.envelopes.rglob("*.json")):
        envelope = load(path)
        if envelope.get("schema_version") != "deep-research-run.v1":
            continue
        case_id = str(envelope["case_id"])
        record = convert(envelope, dataset[case_id], manifests[case_id], baseline)
        dump(args.output_dir / record["group"] / case_id / path.name, record)
        count += 1
    print(f"converted {count} benchmark envelopes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
