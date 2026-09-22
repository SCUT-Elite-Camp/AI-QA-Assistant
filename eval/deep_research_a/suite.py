"""Freeze, validate, preflight, and score CP2 Deep Research A-side assets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


SUITE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SUITE_ROOT.parents[1]
DATASET_PATH = SUITE_ROOT / "datasets" / "cases.v1.json"
MANIFEST_PATH = SUITE_ROOT / "manifests" / "source_manifests.v1.json"
BASELINE_PATH = SUITE_ROOT / "config" / "frozen_baseline.json"
TAXONOMY_PATH = SUITE_ROOT / "failure_taxonomy.json"
DOCUMENTS_DIR = Path(os.getenv(
    "DR_EVAL_DOCUMENTS_DIR",
    PROJECT_ROOT / "data-persistence" / "data" / "documents",
)).resolve()
METADATA_PATH = Path(os.getenv(
    "DR_EVAL_METADATA_PATH",
    PROJECT_ROOT / "data-pipeline" / "confluence_metadata_RAG.json",
)).resolve()
EXPECTED_BEHAVIORS = {
    "answer", "degraded", "refuse", "request_more_information", "conflict_review"
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ))


def normalize_text(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def run_command(*args: str) -> tuple[int, str]:
    completed = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, (completed.stdout or completed.stderr).strip()


def git_blob_sha256(ref: str, path: str) -> str | None:
    completed = subprocess.run(
        ("git", "show", f"{ref}:{path}"),
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    return hashlib.sha256(completed.stdout).hexdigest() if completed.returncode == 0 else None


def load_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    metadata = load_json(METADATA_PATH)
    metadata_by_id = {
        str(item["doc_id"]): item
        for item in metadata.get("pages", [])
        if isinstance(item, dict) and item.get("doc_id")
    }
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(DOCUMENTS_DIR.glob("*.json")):
        payload = load_json(path)
        if isinstance(payload, dict):
            documents[str(payload.get("doc_id") or path.stem)] = payload
    return documents, metadata_by_id


def snapshot_document(
    doc_id: str,
    record: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    # Deliberately mirrors LocalDocumentResolver._searchable_text on the frozen
    # research reference so its content_hash is contract-compatible.
    chunks = record.get("chunks") or []
    chunk_text = " ".join(
        str(chunk.get("text") or chunk.get("chunk_text") or "")
        for chunk in chunks
        if isinstance(chunk, dict)
    )
    searchable = " ".join(
        str(value)
        for value in (record.get("title", ""), record.get("content", ""), chunk_text)
    )
    return {
        "doc_id": doc_id,
        "title": str(record.get("title") or doc_id),
        "source_type": "confluence",
        "authority": "internal",
        "authority_rank": 100,
        "version": str(metadata.get("version") or record.get("version") or record.get("last_updated")),
        "effective_at": record.get("effective_at"),
        "updated_at": metadata.get("last_updated") or record.get("last_updated"),
        "supersedes": list(record.get("supersedes") or []),
        "content_hash": sha256_text(searchable),
        "source_url": str(record.get("source_url") or metadata.get("source_url") or ""),
        "page_id": str(metadata.get("page_id") or record.get("metadata", {}).get("page_id") or ""),
    }


def calculate_manifest_hash(documents: Iterable[dict[str, Any]]) -> str:
    payload = [
        {
            "doc_id": item["doc_id"],
            "version": item.get("version"),
            "content_hash": item["content_hash"],
        }
        for item in sorted(documents, key=lambda item: item["doc_id"])
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return sha256_text(canonical)


def build_manifest_set() -> dict[str, Any]:
    dataset = load_json(DATASET_PATH)
    documents, metadata = load_catalog()
    used_ids = sorted({
        doc_id
        for case in dataset["cases"]
        for doc_id in case["allowed_document_ids"]
    })
    snapshots: dict[str, dict[str, Any]] = {}
    for doc_id in used_ids:
        if doc_id not in documents:
            raise ValueError(f"document missing from local catalog: {doc_id}")
        if doc_id not in metadata:
            raise ValueError(f"document missing from Confluence metadata: {doc_id}")
        snapshots[doc_id] = snapshot_document(doc_id, documents[doc_id], metadata[doc_id])

    manifests: dict[str, Any] = {}
    for case in dataset["cases"]:
        selected = [snapshots[doc_id] for doc_id in sorted(case["allowed_document_ids"])]
        manifests[case["case_id"]] = {
            "schema_version": "research.v2",
            "research_id": case["case_id"],
            "question_sha256": sha256_text(case["question"]),
            "manifest_hash": calculate_manifest_hash(selected),
            "created_at": dataset["frozen_at"],
            "documents": selected,
        }
    return {
        "schema_version": "1.0",
        "manifest_set_id": "cp2-deep-research-manifests.v1",
        "hash_contract": "research.v2 LocalDocumentResolver searchable_text + SourceManifest.calculate_hash",
        "source_metadata": "data-pipeline/confluence_metadata_RAG.json",
        "document_catalog": snapshots,
        "manifests": manifests,
    }


def command_freeze(write: bool, manifests_only: bool = False) -> int:
    manifest_set = build_manifest_set()
    if write:
        write_json(MANIFEST_PATH, manifest_set)
        if manifests_only:
            print(f"wrote {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
            return 0
        baseline = load_json(BASELINE_PATH)
        code, commit = run_command("git", "rev-parse", "HEAD")
        if code == 0:
            baseline["repository"]["head_commit"] = commit
        code, status = run_command("git", "status", "--porcelain=v1", "--untracked-files=all")
        baseline["repository"]["working_tree_dirty_at_freeze"] = bool(status) if code == 0 else None
        baseline["repository"]["working_tree_status_sha256"] = sha256_text(status)
        baseline["generation_config_sha256"] = sha256_json(baseline["generation"])
        baseline["frozen_at"] = load_json(DATASET_PATH)["frozen_at"]
        write_json(BASELINE_PATH, baseline)
        print(f"wrote {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
        print(f"updated {BASELINE_PATH.relative_to(PROJECT_ROOT)}")
        return 0

    if not MANIFEST_PATH.exists():
        print("manifest file is absent; run freeze --write", file=sys.stderr)
        return 1
    current = load_json(MANIFEST_PATH)
    if current != manifest_set:
        print("frozen SourceManifest drift detected; review before freeze --write", file=sys.stderr)
        return 1
    print("frozen SourceManifests match the local Confluence snapshot")
    return 0


def _case_errors(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "case_id", "category", "question", "source_manifest", "expected_behavior",
        "required_facts", "forbidden_claims", "key_source_locations",
        "allowed_document_ids", "forbidden_document_ids",
    }
    missing = required - set(case)
    if missing:
        errors.append(f"missing fields {sorted(missing)}")
    if case.get("expected_behavior") not in EXPECTED_BEHAVIORS:
        errors.append("invalid expected_behavior")
    allowed = case.get("allowed_document_ids", [])
    forbidden = case.get("forbidden_document_ids", [])
    if not allowed or len(allowed) != len(set(allowed)):
        errors.append("allowed_document_ids must be non-empty and unique")
    if set(allowed) & set(forbidden):
        errors.append("allowed and forbidden document scopes overlap")
    fact_ids = [fact.get("fact_id") for fact in case.get("required_facts", [])]
    if len(fact_ids) != len(set(fact_ids)):
        errors.append("required fact ids are not unique")
    return errors


def validate_assets(verbose: bool = True) -> list[str]:
    errors: list[str] = []
    for path in (DATASET_PATH, MANIFEST_PATH, BASELINE_PATH, TAXONOMY_PATH):
        if not path.is_file():
            errors.append(f"missing asset: {path.relative_to(PROJECT_ROOT)}")
    if errors:
        return errors

    dataset = load_json(DATASET_PATH)
    manifest_set = load_json(MANIFEST_PATH)
    baseline = load_json(BASELINE_PATH)
    cases = dataset.get("cases", [])
    if dataset.get("case_count") != 18 or len(cases) != 18:
        errors.append("dataset must contain exactly 18 cases")
    case_ids = [case.get("case_id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("case ids are not unique")
    groups = [group.get("id") for group in baseline.get("experiment", {}).get("groups", [])]
    if groups != ["G1", "G2", "G3"]:
        errors.append("baseline groups must be exactly G1/G2/G3")
    if baseline.get("generation_config_sha256") != sha256_json(baseline.get("generation", {})):
        errors.append("frozen generation config hash mismatch")
    g1_prompt = baseline.get("prompts", {}).get("g1_answer", {})
    for path_key, hash_key in (("path", "sha256"), ("assembly_path", "assembly_sha256")):
        if path_key == "assembly_path" and g1_prompt.get("assembly_git_ref"):
            if git_blob_sha256(g1_prompt["assembly_git_ref"], g1_prompt[path_key]) != g1_prompt.get("assembly_git_sha256"):
                errors.append("frozen G1 assembly source hash mismatch")
            continue
        prompt_path = PROJECT_ROOT / str(g1_prompt.get(path_key, ""))
        if not prompt_path.is_file():
            errors.append(f"G1 prompt source missing: {g1_prompt.get(path_key)}")
        elif hashlib.sha256(prompt_path.read_bytes()).hexdigest() != g1_prompt.get(hash_key):
            errors.append(f"G1 prompt source drift: {g1_prompt.get(path_key)}")
    research_reference = baseline.get("implementation", {}).get("research_reference", {})
    ref = str(research_reference.get("git_ref", ""))
    code, resolved_ref = run_command("git", "rev-parse", "--verify", ref)
    if code != 0 or resolved_ref != research_reference.get("commit"):
        errors.append("frozen research implementation ref is missing or moved")
    for prompt_name in ("planner", "worker", "report"):
        prompt = baseline.get("prompts", {}).get(prompt_name, {})
        if git_blob_sha256(str(prompt.get("git_ref", ref)), str(prompt.get("path", ""))) != prompt.get("sha256"):
            errors.append(f"frozen {prompt_name} source hash mismatch")

    documents, metadata = load_catalog()
    manifests = manifest_set.get("manifests", {})
    for case in cases:
        cid = case.get("case_id", "<unknown>")
        errors.extend(f"{cid}: {item}" for item in _case_errors(case))
        manifest = manifests.get(cid)
        if not manifest:
            errors.append(f"{cid}: SourceManifest missing")
            continue
        if case.get("source_manifest") != f"manifest:{cid}":
            errors.append(f"{cid}: source_manifest reference mismatch")
        manifest_docs = manifest.get("documents", [])
        manifest_ids = [item.get("doc_id") for item in manifest_docs]
        if sorted(manifest_ids) != sorted(case.get("allowed_document_ids", [])):
            errors.append(f"{cid}: manifest documents do not equal allowlist")
        if manifest.get("manifest_hash") != calculate_manifest_hash(manifest_docs):
            errors.append(f"{cid}: manifest hash mismatch")
        if manifest.get("question_sha256") != sha256_text(case.get("question", "")):
            errors.append(f"{cid}: question hash mismatch")
        snapshots = {item["doc_id"]: item for item in manifest_docs}
        for doc_id, frozen in snapshots.items():
            if doc_id not in documents or doc_id not in metadata:
                errors.append(f"{cid}: local source missing for {doc_id}")
                continue
            live = snapshot_document(doc_id, documents[doc_id], metadata[doc_id])
            for field in ("version", "content_hash", "source_url", "page_id"):
                if frozen.get(field) != live.get(field):
                    errors.append(f"{cid}: {doc_id} {field} drift")
        for location in case.get("key_source_locations", []):
            doc_id = location.get("doc_id")
            chunk_id = location.get("chunk_id")
            if doc_id not in case.get("allowed_document_ids", []):
                errors.append(f"{cid}: key location outside manifest: {doc_id}")
                continue
            record = documents.get(doc_id, {})
            chunk = next(
                (item for item in record.get("chunks", []) if item.get("chunk_id") == chunk_id),
                None,
            )
            if chunk is None:
                errors.append(f"{cid}: key chunk not found: {chunk_id}")
            elif normalize_text(location.get("quote", "")) not in normalize_text(chunk.get("text", "")):
                errors.append(f"{cid}: quote not found in {chunk_id}: {location.get('quote')}")

    required_files = [
        SUITE_ROOT / "schemas" / "case.schema.json",
        SUITE_ROOT / "schemas" / "run_record.schema.json",
        SUITE_ROOT / "schemas" / "judge_output.schema.json",
        SUITE_ROOT / "prompts" / "model_judge.v1.md",
        SUITE_ROOT / "templates" / "g1_g2_g3_results.csv",
    ]
    for path in required_files:
        if not path.is_file():
            errors.append(f"missing asset: {path.relative_to(PROJECT_ROOT)}")
    if verbose and not errors:
        categories = sorted({case["category"] for case in cases})
        print(f"validated 18 cases, {len(manifests)} manifests, {len(categories)} categories")
    return errors


def command_validate() -> int:
    errors = validate_assets()
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print("A-side evaluation assets are internally consistent and source hashes match")
    return 0


def command_preflight(require_all_groups: bool) -> int:
    errors = validate_assets(verbose=False)
    checks: dict[str, Any] = {
        "assets_valid": not errors,
        "asset_errors": errors,
        "python": platform.python_version(),
        "documents_dir": str(DOCUMENTS_DIR),
        "document_count": len(list(DOCUMENTS_DIR.glob("*.json"))),
    }
    code, docker_version = run_command("docker", "version", "--format", "{{.Server.Version}}")
    checks["docker"] = {"ready": code == 0, "server_version": docker_version if code == 0 else None}
    code, milvus = run_command("docker", "inspect", "-f", "{{.State.Health.Status}}", "milvus-standalone")
    if code != 0:
        code, milvus = run_command("docker", "inspect", "-f", "{{.State.Status}}", "milvus-standalone")
    checks["milvus"] = {"ready": code == 0 and milvus in {"healthy", "running"}, "status": milvus or "not_found"}
    checks["groups"] = {
        "G1": (PROJECT_ROOT / "agent" / "agent" / "api" / "chat_routes.py").is_file(),
        "G2": (PROJECT_ROOT / "agent" / "deep_research").is_dir(),
        "G3": (PROJECT_ROOT / "agent" / "deep_research").is_dir()
            and any((PROJECT_ROOT / "toolset").rglob("*page*index*.py")),
    }
    baseline = load_json(BASELINE_PATH)
    frozen_ref = str(
        baseline.get("implementation", {}).get("research_reference", {}).get("git_ref", "")
    )
    ref_code, resolved_ref = run_command("git", "rev-parse", "--verify", frozen_ref)
    checks["research_reference_available"] = (
        ref_code == 0
        and resolved_ref
        == baseline.get("implementation", {}).get("research_reference", {}).get("commit")
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    required_ok = checks["assets_valid"] and checks["docker"]["ready"] and checks["milvus"]["ready"]
    if require_all_groups:
        required_ok = required_ok and all(checks["groups"].values())
    return 0 if required_ok else 1


def _has_cycle(tasks: list[dict[str, Any]]) -> bool:
    graph = {task.get("task_id"): set(task.get("depends_on", [])) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, set()):
            if dep not in graph or visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _ratio(numerator: int, denominator: int, empty: float = 1.0) -> float:
    return round(numerator / denominator, 6) if denominator else empty


def _contains_any(text: str, patterns: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(pattern) in normalized for pattern in patterns)


def score_run(record: dict[str, Any]) -> dict[str, Any]:
    dataset = load_json(DATASET_PATH)
    manifest_set = load_json(MANIFEST_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    case = next((item for item in dataset["cases"] if item["case_id"] == record.get("case_id")), None)
    if case is None:
        raise ValueError(f"unknown case_id: {record.get('case_id')}")
    manifest = manifest_set["manifests"][case["case_id"]]
    allowed = set(case["allowed_document_ids"])
    facts = {item["fact_id"]: item for item in case["required_facts"]}
    key_docs = {item["doc_id"] for item in case["key_source_locations"]}
    key_chunks = {item["chunk_id"] for item in case["key_source_locations"]}
    snapshot_by_doc = {item["doc_id"]: item for item in manifest["documents"]}

    invariant_errors: list[str] = []
    request = record.get("request", {})
    if request.get("question") != case["question"]:
        invariant_errors.append("question_text")
    if request.get("question_sha256") != sha256_text(case["question"]):
        invariant_errors.append("question_sha256")
    if request.get("manifest_hash") != manifest["manifest_hash"]:
        invariant_errors.append("manifest_hash")
    if set(request.get("allowed_document_ids", [])) != allowed:
        invariant_errors.append("allowed_document_ids")
    if set(request.get("forbidden_document_ids", [])) != set(case["forbidden_document_ids"]):
        invariant_errors.append("forbidden_document_ids")

    tasks = record.get("plan", {}).get("tasks", [])
    covered = {fact for task in tasks for fact in task.get("covers", []) if fact in facts}
    normalized_queries = [normalize_text(task.get("query", "")) for task in tasks]
    duplicates = len(normalized_queries) - len(set(normalized_queries))
    executable = sum(bool(task.get("task_id") and task.get("query")) for task in tasks)
    plan_layer = {
        "question_coverage": _ratio(len(covered), len(facts)),
        "duplicate_task_rate": _ratio(duplicates, len(tasks), empty=0.0),
        "dependency_valid": not _has_cycle(tasks),
        "task_executable_rate": _ratio(executable, len(tasks), empty=0.0),
    }

    hits = record.get("retrieval_hits", [])
    hit_docs = [str(item.get("doc_id", "")) for item in hits]
    hit_chunks = {str(item.get("chunk_id", "")) for item in hits}
    relevant_ranks = [int(item.get("rank", index + 1)) for index, item in enumerate(hits) if item.get("doc_id") in key_docs]
    hit_key_docs = key_docs & set(hit_docs)
    permission_hit_count = sum(doc_id not in allowed for doc_id in hit_docs)
    retrieval_layer = {
        "correct_document_recall": _ratio(len(hit_key_docs), len(key_docs)),
        "evidence_recall_at_k": _ratio(len(key_chunks & hit_chunks), len(key_chunks)),
        "mrr": round(1.0 / min(relevant_ranks), 6) if relevant_ranks else 0.0,
        "noise_ratio": _ratio(sum(doc_id not in key_docs for doc_id in hit_docs), len(hit_docs), empty=0.0),
        "permission_leak_count": permission_hit_count,
    }

    evidence = record.get("verified_evidence", [])
    evidence_ids = {item.get("evidence_id") for item in evidence}
    evidence_fact_ids = {fact for item in evidence for fact in item.get("supports_fact_ids", []) if fact in facts}
    original_reads = sum(item.get("source_method") in {"read_document_range", "local_original_read"} for item in evidence)
    valid_locator_count = 0
    permission_evidence_count = 0
    for item in evidence:
        doc_id = item.get("doc_id")
        frozen = snapshot_by_doc.get(doc_id)
        if frozen is None:
            permission_evidence_count += 1
            continue
        if (
            item.get("locator")
            and str(item.get("document_version")) == str(frozen.get("version"))
            and item.get("content_hash") == frozen.get("content_hash")
        ):
            valid_locator_count += 1
    expected_conflict = case["expected_behavior"] == "conflict_review"
    conflict_statuses = {item.get("conflict_status") for item in evidence}
    conflict_ok = (not expected_conflict) or bool({"conflict", "version_evolution"} & conflict_statuses)
    evidence_layer = {
        "original_read_rate": _ratio(original_reads, len(evidence)),
        "required_fact_coverage": _ratio(len(evidence_fact_ids), len(facts)),
        "locator_valid_rate": _ratio(valid_locator_count, len(evidence)),
        "conflict_identified": conflict_ok,
        "permission_leak_count": permission_evidence_count,
    }

    report = record.get("report", {})
    report_text = str(report.get("text", ""))
    deterministic_facts = {
        fact_id for fact_id, fact in facts.items() if _contains_any(report_text, fact["match_any"])
    }
    forbidden_matches = [
        item["description"] for item in case["forbidden_claims"]
        if _contains_any(report_text, item["match_any"])
    ]
    judge = record.get("model_judge") or {}
    report_layer = {
        "expected_behavior_match": report.get("behavior") == case["expected_behavior"],
        "deterministic_required_fact_coverage": _ratio(len(deterministic_facts), len(facts)),
        "forbidden_claim_matches": forbidden_matches,
        "correctness": judge.get("correctness"),
        "completeness": judge.get("completeness"),
        "faithfulness": judge.get("faithfulness"),
        "answer_relevance": judge.get("answer_relevance"),
        "limitation_disclosure": judge.get("limitation_disclosure"),
        "conflict_handling": judge.get("conflict_handling"),
        "limitations_disclosed": bool(report.get("limitations_disclosed")),
    }

    claims = record.get("claims", [])
    factual_claims = [item for item in claims if item.get("factual")]
    citations = record.get("citations", [])
    cited_claim_ids = {claim_id for item in citations for claim_id in item.get("claim_ids", [])}
    unsupported_claim_ids = {
        item.get("claim_id") for item in factual_claims
        if not item.get("evidence_ids") or not set(item.get("evidence_ids", [])) <= evidence_ids
    }
    unsupported_claim_ids.update(judge.get("unsupported_claim_ids", []))
    supported_citations = sum(bool(item.get("supports_claim")) for item in citations)
    required_links = [item for item in citations if item.get("source_url")]
    open_links = sum(item.get("link_status") == "open" for item in required_links)
    broken_links = sum(item.get("link_status") in {"broken", "unchecked"} for item in required_links)
    locator_matches = 0
    permission_citation_count = 0
    for item in citations:
        if item.get("doc_id") not in allowed:
            permission_citation_count += 1
        cited_evidence = [ev for ev in evidence if ev.get("evidence_id") in item.get("evidence_ids", [])]
        if item.get("locator") and any(ev.get("locator") == item.get("locator") for ev in cited_evidence):
            locator_matches += 1
    missing_citation_count = sum(item.get("claim_id") not in cited_claim_ids for item in factual_claims)
    citation_layer = {
        "citation_support_rate": _ratio(supported_citations, len(citations)),
        "factual_claim_citation_coverage": _ratio(len({item.get("claim_id") for item in factual_claims} & cited_claim_ids), len(factual_claims)),
        "link_open_rate": _ratio(open_links, len(required_links)),
        "locator_match_rate": _ratio(locator_matches, len(citations)),
        "missing_citation_count": missing_citation_count,
        "broken_citation_count": sum(not item.get("supports_claim") for item in citations),
        "unopenable_source_link_count": broken_links,
        "permission_leak_count": permission_citation_count,
        "unsupported_factual_claim_count": len(unsupported_claim_ids),
    }

    runtime = record.get("runtime_metrics", {})
    runtime_layer = {
        key: runtime.get(key)
        for key in (
            "total_latency_ms", "stage_latency_ms", "search_calls", "read_calls",
            "tool_calls", "input_tokens", "output_tokens", "retries", "fallbacks",
            "checkpoint_recoveries", "provider_failures",
        )
    }
    runtime_layer.update({
        "terminal_status": record.get("terminal_status"),
        "failure_stage": record.get("failure_stage"),
        "error": record.get("error"),
    })

    permission_leaks = (
        retrieval_layer["permission_leak_count"]
        + evidence_layer["permission_leak_count"]
        + citation_layer["permission_leak_count"]
    )
    hard_values = {
        "permission_leak_count": permission_leaks,
        "broken_citation_count": citation_layer["broken_citation_count"],
        "unsupported_factual_claim_count": citation_layer["unsupported_factual_claim_count"],
        "unopenable_source_link_count": citation_layer["unopenable_source_link_count"],
        "factual_claim_citation_coverage": citation_layer["factual_claim_citation_coverage"],
        "faithfulness": report_layer["faithfulness"],
        "answer_relevance": report_layer["answer_relevance"],
    }
    hard_results: dict[str, Any] = {}
    for name, rule in taxonomy["hard_gates"].items():
        value = hard_values[name]
        passed = None if value is None else (
            value == rule["threshold"] if rule["operator"] == "eq" else value >= rule["threshold"]
        )
        hard_results[name] = {"value": value, "passed": passed, **rule}

    failure_codes: list[str] = []
    if plan_layer["question_coverage"] < 1: failure_codes.append("PLAN_COVERAGE")
    if plan_layer["duplicate_task_rate"] > 0: failure_codes.append("PLAN_DUPLICATION")
    if not plan_layer["dependency_valid"]: failure_codes.append("PLAN_DEPENDENCY")
    if permission_leaks: failure_codes.append("RETRIEVAL_PERMISSION_LEAK")
    if retrieval_layer["correct_document_recall"] < 1: failure_codes.append("RETRIEVAL_DOCUMENT_MISS")
    elif retrieval_layer["evidence_recall_at_k"] < 1: failure_codes.append("RETRIEVAL_SECTION_MISS")
    if retrieval_layer["noise_ratio"] > 0.5: failure_codes.append("RETRIEVAL_NOISE")
    if evidence_layer["original_read_rate"] < 1: failure_codes.append("EVIDENCE_ORIGINAL_NOT_READ")
    if evidence_layer["required_fact_coverage"] < 1: failure_codes.append("EVIDENCE_INSUFFICIENT")
    if evidence_layer["locator_valid_rate"] < 1: failure_codes.append("EVIDENCE_WRONG_LOCATOR")
    if not evidence_layer["conflict_identified"]: failure_codes.append("EVIDENCE_CONFLICT_MISCLASSIFIED")
    if forbidden_matches or (judge.get("correctness") or 5) < 4: failure_codes.append("REPORT_INCORRECT")
    if report_layer["deterministic_required_fact_coverage"] < 1 or (judge.get("completeness") or 5) < 4: failure_codes.append("REPORT_INCOMPLETE")
    if unsupported_claim_ids or (judge.get("faithfulness") or 5) < 4: failure_codes.append("REPORT_UNFAITHFUL")
    if missing_citation_count: failure_codes.append("CITATION_MISSING")
    if citation_layer["broken_citation_count"]: failure_codes.append("CITATION_UNSUPPORTED")
    if broken_links: failure_codes.append("CITATION_BROKEN_LINK")
    if record.get("terminal_status") == "timeout": failure_codes.append("RUNTIME_TIMEOUT")
    if (runtime.get("provider_failures") or 0) > 0: failure_codes.append("RUNTIME_PROVIDER_FAILURE")
    if (runtime.get("fallbacks") or 0) > 0: failure_codes.append("RUNTIME_FALLBACK")
    if record.get("failure_stage") == "recovery": failure_codes.append("RUNTIME_RECOVERY_FAILURE")
    ordered = [code for code in taxonomy["root_cause_order"] if code in set(failure_codes)]
    hard_gate_pass = all(item["passed"] is True for item in hard_results.values())
    return {
        "schema_version": "1.0",
        "run_id": record.get("run_id"),
        "case_id": case["case_id"],
        "group": record.get("group"),
        "invariant_errors": invariant_errors,
        "layers": {
            "plan": plan_layer, "retrieval": retrieval_layer, "evidence": evidence_layer,
            "report": report_layer, "citation": citation_layer, "runtime": runtime_layer,
        },
        "hard_gates": hard_results,
        "hard_gate_pass": hard_gate_pass and not invariant_errors,
        "failure_codes": ordered,
        "root_cause": ordered[0] if ordered else None,
        "downstream_effects": ordered[1:],
        "requires_codex_review": bool(
            invariant_errors or forbidden_matches or ordered
            or any(item["passed"] is None for item in hard_results.values())
        ),
    }


def command_score(path: Path, output: Path | None) -> int:
    result = score_run(load_json(path))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
    else:
        print(rendered, end="")
    return 0 if result["hard_gate_pass"] else 2


def _nested(payload: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _csv_row(record: dict[str, Any], score: dict[str, Any]) -> dict[str, Any]:
    dataset = load_json(DATASET_PATH)
    baseline = load_json(BASELINE_PATH)
    case = next(item for item in dataset["cases"] if item["case_id"] == record["case_id"])
    plan = score["layers"]["plan"]
    retrieval = score["layers"]["retrieval"]
    evidence = score["layers"]["evidence"]
    report = score["layers"]["report"]
    citation = score["layers"]["citation"]
    runtime = score["layers"]["runtime"]
    error = record.get("error") or {}
    return {
        "baseline_id": baseline["baseline_id"], "dataset_version": baseline["dataset_version"],
        "run_id": record.get("run_id"), "case_id": case["case_id"], "category": case["category"],
        "group": record.get("group"), "repeat": record.get("repeat"),
        "question_sha256": _nested(record, "request", "question_sha256"),
        "manifest_hash": _nested(record, "request", "manifest_hash"),
        "generation_config_hash": _nested(record, "environment", "generation_config_hash"),
        "git_commit": _nested(record, "environment", "git_commit"),
        "provider": _nested(record, "environment", "provider"),
        "model": _nested(record, "environment", "model"),
        "model_revision": _nested(record, "environment", "model_revision"),
        "prompt_hashes": json.dumps(_nested(record, "environment", "prompt_hashes", default={}), sort_keys=True),
        "embedding_revision": _nested(record, "environment", "embedding_revision"),
        "terminal_status": record.get("terminal_status"), "expected_behavior": case["expected_behavior"],
        "observed_behavior": _nested(record, "report", "behavior"),
        "plan_coverage": plan["question_coverage"], "plan_duplicate_rate": plan["duplicate_task_rate"],
        "plan_dependency_valid": plan["dependency_valid"], "plan_executable_rate": plan["task_executable_rate"],
        "retrieval_document_recall": retrieval["correct_document_recall"],
        "evidence_recall_at_k": retrieval["evidence_recall_at_k"], "mrr": retrieval["mrr"],
        "noise_ratio": retrieval["noise_ratio"],
        "permission_leak_count": sum(layer["permission_leak_count"] for layer in (retrieval, evidence, citation)),
        "original_read_rate": evidence["original_read_rate"],
        "evidence_fact_coverage": evidence["required_fact_coverage"],
        "locator_valid_rate": evidence["locator_valid_rate"],
        "conflict_handling_score": report["conflict_handling"],
        "correctness": report["correctness"], "completeness": report["completeness"],
        "faithfulness": report["faithfulness"], "answer_relevance": report["answer_relevance"],
        "limitation_disclosure": report["limitation_disclosure"],
        "citation_support_rate": citation["citation_support_rate"],
        "factual_claim_citation_coverage": citation["factual_claim_citation_coverage"],
        "link_open_rate": citation["link_open_rate"], "locator_match_rate": citation["locator_match_rate"],
        "total_latency_ms": runtime["total_latency_ms"], "search_calls": runtime["search_calls"],
        "read_calls": runtime["read_calls"], "tool_calls": runtime["tool_calls"],
        "input_tokens": runtime["input_tokens"], "output_tokens": runtime["output_tokens"],
        "retries": runtime["retries"], "fallbacks": runtime["fallbacks"],
        "checkpoint_recoveries": runtime["checkpoint_recoveries"],
        "provider_failures": runtime["provider_failures"], "hard_gate_pass": score["hard_gate_pass"],
        "root_cause": score["root_cause"],
        "downstream_effects": "|".join(score["downstream_effects"]),
        "failure_stage": record.get("failure_stage"), "error_code": error.get("code"),
    }


def command_batch_score(
    records_dir: Path,
    output_dir: Path,
    allow_incomplete: bool,
    groups: list[str] | None = None,
) -> int:
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.rglob("*.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and {"run_id", "case_id", "group"} <= set(payload):
            records.append(payload)
    if not records:
        print(f"no run records found under {records_dir}", file=sys.stderr)
        return 1

    dataset = load_json(DATASET_PATH)
    baseline = load_json(BASELINE_PATH)
    repeats = int(baseline["experiment"]["repeats_per_case"])
    selected_groups = groups or [group["id"] for group in baseline["experiment"]["groups"]]
    expected = {
        (case["case_id"], group["id"], repeat)
        for case in dataset["cases"]
        for group in baseline["experiment"]["groups"]
        if group["id"] in selected_groups
        for repeat in range(1, repeats + 1)
    }
    seen: dict[tuple[str, str, int], dict[str, Any]] = {}
    batch_errors: list[str] = []
    for record in records:
        key = (str(record.get("case_id")), str(record.get("group")), int(record.get("repeat", 0)))
        if key in seen:
            batch_errors.append(f"duplicate run coordinate: {key}")
        seen[key] = record
    missing = sorted(expected - set(seen))
    unexpected = sorted(key for key in set(seen) - expected if key[1] in selected_groups)
    if missing and not allow_incomplete:
        batch_errors.append(f"missing {len(missing)} required run coordinates")
    if unexpected:
        batch_errors.append(f"unexpected run coordinates: {unexpected[:5]}")

    invariant_fields = [
        ("request", "question"), ("request", "question_sha256"),
        ("request", "manifest_hash"), ("request", "allowed_document_ids"),
        ("request", "forbidden_document_ids"), ("environment", "provider"),
        ("environment", "model"), ("environment", "model_revision"),
        ("environment", "generation_config_hash"), ("environment", "embedding_revision"),
    ]
    for case in dataset["cases"]:
        case_records = [record for record in records if record.get("case_id") == case["case_id"]]
        for field in invariant_fields:
            values = {
                json.dumps(_nested(record, *field), ensure_ascii=False, sort_keys=True)
                for record in case_records
            }
            if len(values) > 1:
                batch_errors.append(f"{case['case_id']}: invariant drift at {'.'.join(field)}")
        for group in ("G1", "G2", "G3"):
            group_records = [record for record in case_records if record.get("group") == group]
            prompt_values = {
                json.dumps(_nested(record, "environment", "prompt_hashes", default={}), sort_keys=True)
                for record in group_records
            }
            if len(prompt_values) > 1:
                batch_errors.append(f"{case['case_id']} {group}: prompt hash drift across repeats")

    scored = [score_run(record) for record in records]
    rows = [_csv_row(record, score) for record, score in zip(records, scored)]
    header = next(csv.reader([
        (SUITE_ROOT / "templates" / "g1_g2_g3_results.csv").read_text(encoding="utf-8").splitlines()[0]
    ]))
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "scores.jsonl").open("w", encoding="utf-8") as handle:
        for result in scored:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    group_summary: dict[str, Any] = {}
    metric_paths = {
        "correctness": ("report", "correctness"),
        "completeness": ("report", "completeness"),
        "faithfulness": ("report", "faithfulness"),
        "answer_relevance": ("report", "answer_relevance"),
        "evidence_recall_at_k": ("retrieval", "evidence_recall_at_k"),
        "total_latency_ms": ("runtime", "total_latency_ms"),
        "tool_calls": ("runtime", "tool_calls"),
    }
    for group in selected_groups:
        selected = [result for result in scored if result.get("group") == group]
        averages: dict[str, float | None] = {}
        for name, path in metric_paths.items():
            values = [_nested(item["layers"], *path) for item in selected]
            numeric = [float(value) for value in values if isinstance(value, (int, float))]
            averages[name] = round(sum(numeric) / len(numeric), 6) if numeric else None
        group_summary[group] = {
            "run_count": len(selected),
            "hard_gate_pass_count": sum(item["hard_gate_pass"] for item in selected),
            "averages": averages,
        }
    summary = {
        "schema_version": "1.0", "record_count": len(records),
        "expected_record_count": len(expected), "missing_coordinates": missing,
        "batch_errors": batch_errors, "groups": group_summary,
        "all_hard_gates_pass": all(item["hard_gate_pass"] for item in scored),
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not batch_errors and summary["all_hard_gates_pass"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze", help="check or refresh frozen manifests")
    freeze_parser.add_argument("--write", action="store_true", help="write the intentional new snapshot")
    freeze_parser.add_argument(
        "--manifests-only", action="store_true",
        help="refresh SourceManifests without changing the frozen repository baseline",
    )
    subparsers.add_parser("validate", help="validate all A-side assets and local source hashes")
    preflight_parser = subparsers.add_parser("preflight", help="check runtime prerequisites")
    preflight_parser.add_argument("--require-all-groups", action="store_true")
    score_parser = subparsers.add_parser("score", help="score one raw six-layer run record")
    score_parser.add_argument("record", type=Path)
    score_parser.add_argument("--output", type=Path)
    batch_parser = subparsers.add_parser("batch-score", help="score and compare a G1/G2/G3 record directory")
    batch_parser.add_argument("records_dir", type=Path)
    batch_parser.add_argument("--output-dir", type=Path, required=True)
    batch_parser.add_argument("--allow-incomplete", action="store_true")
    batch_parser.add_argument("--groups", nargs="+", choices=("G1", "G2", "G3"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "freeze":
        return command_freeze(args.write, args.manifests_only)
    if args.command == "validate":
        return command_validate()
    if args.command == "preflight":
        return command_preflight(args.require_all_groups)
    if args.command == "score":
        return command_score(args.record, args.output)
    if args.command == "batch-score":
        return command_batch_score(
            args.records_dir, args.output_dir, args.allow_incomplete, args.groups
        )
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
