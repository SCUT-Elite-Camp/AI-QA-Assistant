from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path


SUITE_PATH = Path(__file__).resolve().parents[1] / "suite.py"
SPEC = importlib.util.spec_from_file_location("deep_research_a_suite", SUITE_PATH)
assert SPEC and SPEC.loader
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


def perfect_record(case_id: str = "DR-A-001") -> dict:
    dataset = suite.load_json(suite.DATASET_PATH)
    manifests = suite.load_json(suite.MANIFEST_PATH)["manifests"]
    case = next(item for item in dataset["cases"] if item["case_id"] == case_id)
    manifest = manifests[case_id]
    frozen_by_id = {item["doc_id"]: item for item in manifest["documents"]}
    locations = case["key_source_locations"]
    fact_ids = [item["fact_id"] for item in case["required_facts"]]
    evidence = []
    for index, location in enumerate(locations, start=1):
        frozen = frozen_by_id[location["doc_id"]]
        evidence.append({
            "evidence_id": f"ev-{index}",
            "doc_id": location["doc_id"],
            "document_version": frozen["version"],
            "content_hash": frozen["content_hash"],
            "locator": location["chunk_id"],
            "excerpt": location["quote"],
            "source_method": "read_document_range",
            "supports_fact_ids": fact_ids if index == 1 else [],
            "conflict_status": (
                "version_evolution" if case["expected_behavior"] == "conflict_review" else "none"
            ),
        })
    claims = [
        {"claim_id": f"claim-{index}", "text": fact["description"], "factual": True, "evidence_ids": ["ev-1"]}
        for index, fact in enumerate(case["required_facts"], start=1)
    ]
    citations = [
        {
            "citation_id": f"cite-{index}",
            "claim_ids": [claim["claim_id"]],
            "evidence_ids": ["ev-1"],
            "doc_id": evidence[0]["doc_id"],
            "locator": evidence[0]["locator"],
            "source_url": frozen_by_id[evidence[0]["doc_id"]]["source_url"],
            "link_status": "open",
            "supports_claim": True,
        }
        for index, claim in enumerate(claims, start=1)
    ]
    report_text = "；".join(fact["match_any"][0] for fact in case["required_facts"])
    return {
        "schema_version": "1.0",
        "run_id": "test-perfect",
        "group": "G2",
        "case_id": case_id,
        "repeat": 1,
        "environment": {
            "git_commit": "test", "git_dirty": False, "python_version": "test",
            "docker_version": "test", "provider": "test", "model": "test",
            "model_revision": "test", "generation_config_hash": "test",
            "prompt_hashes": {}, "embedding_revision": "test",
        },
        "request": {
            "question": case["question"],
            "question_sha256": suite.sha256_text(case["question"]),
            "manifest_hash": manifest["manifest_hash"],
            "allowed_document_ids": case["allowed_document_ids"],
            "forbidden_document_ids": case["forbidden_document_ids"],
        },
        "plan": {"tasks": [
            {"task_id": f"task-{index}", "query": fact["description"], "covers": [fact["fact_id"]], "depends_on": []}
            for index, fact in enumerate(case["required_facts"], start=1)
        ]},
        "retrieval_hits": [
            {"rank": index, "doc_id": item["doc_id"], "chunk_id": item["chunk_id"], "score": 1.0, "search_path": "hybrid"}
            for index, item in enumerate(locations, start=1)
        ],
        "observations": [],
        "verified_evidence": evidence,
        "claims": claims,
        "report": {"text": report_text, "behavior": case["expected_behavior"], "limitations_disclosed": True},
        "citations": citations,
        "events": [],
        "runtime_metrics": {
            "total_latency_ms": 100, "stage_latency_ms": {}, "search_calls": 1,
            "read_calls": len(evidence), "tool_calls": len(evidence) + 1,
            "input_tokens": 10, "output_tokens": 10, "retries": 0, "fallbacks": 0,
            "checkpoint_recoveries": 0, "provider_failures": 0,
        },
        "model_judge": {
            "judge_version": "judge.v1", "correctness": 5, "completeness": 5,
            "faithfulness": 5, "answer_relevance": 5, "limitation_disclosure": 5,
            "conflict_handling": 5, "required_fact_ids_supported": fact_ids,
            "unsupported_claim_ids": [], "rationale": "test",
        },
        "terminal_status": "completed",
        "failure_stage": None,
        "error": None,
    }


class DeepResearchASuiteTests(unittest.TestCase):
    def test_assets_match_frozen_sources(self) -> None:
        self.assertEqual(suite.validate_assets(verbose=False), [])

    def test_manifest_hash_is_canonical_and_stable(self) -> None:
        payload = suite.load_json(suite.MANIFEST_PATH)
        for manifest in payload["manifests"].values():
            self.assertEqual(
                suite.calculate_manifest_hash(manifest["documents"]),
                manifest["manifest_hash"],
            )

    def test_complete_supported_run_passes_hard_gates(self) -> None:
        result = suite.score_run(perfect_record())
        self.assertTrue(result["hard_gate_pass"])
        self.assertEqual(result["failure_codes"], [])
        self.assertFalse(result["requires_codex_review"])

    def test_permission_leak_is_a_root_cause(self) -> None:
        record = perfect_record()
        record["retrieval_hits"].append({
            "rank": 99,
            "doc_id": "forbidden-doc",
            "chunk_id": "forbidden-doc_chunk_0",
            "score": 0.5,
            "search_path": "hybrid",
        })
        result = suite.score_run(record)
        self.assertFalse(result["hard_gate_pass"])
        self.assertEqual(result["root_cause"], "RETRIEVAL_PERMISSION_LEAK")

    def test_incomplete_batch_dry_run_emits_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = root / "records"
            output = root / "output"
            records.mkdir()
            (records / "one.json").write_text(
                json.dumps(perfect_record(), ensure_ascii=False), encoding="utf-8"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = suite.command_batch_score(records, output, allow_incomplete=True)
            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "results.csv").is_file())
            self.assertTrue((output / "scores.jsonl").is_file())
            summary = suite.load_json(output / "summary.json")
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["expected_record_count"], 162)


if __name__ == "__main__":
    unittest.main()
