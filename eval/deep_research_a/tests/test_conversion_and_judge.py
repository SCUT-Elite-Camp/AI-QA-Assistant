from __future__ import annotations

import sys
from pathlib import Path


SUITE_ROOT = Path(__file__).resolve().parents[1]
if str(SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUITE_ROOT))

from convert_benchmark_runs import GROUPS, convert
from judge_records import parse_json


def test_all_benchmark_groups_have_six_layer_names() -> None:
    assert GROUPS == {
        "fast_chat": "G1",
        "deep_research_current": "G2",
        "deep_research_page_index": "G3",
    }


def test_fast_chat_conversion_restores_stable_evidence_identity() -> None:
    envelope = {
        "group": "fast_chat",
        "run_id": "run-1",
        "case_id": "DR-A-001",
        "repetition": 1,
        "elapsed_ms": 123,
        "result": {
            "response": {"answer": "利润保持稳定。[1]", "status": "success"},
            "citations": [
                {
                    "number": 1,
                    "doc_id": "doc-a",
                    "chunk_id": "doc-a::chunk_1",
                    "chunk_index": 1,
                    "snippet": "利润保持稳定。",
                    "source_url": "https://example.test/doc-a",
                    "score": 0.9,
                }
            ],
            "source_checks": [
                {"url": "https://example.test/doc-a", "ok": True}
            ],
        },
    }
    case = {
        "question": "利润如何？",
        "allowed_document_ids": ["doc-a"],
        "forbidden_document_ids": [],
        "required_facts": [
            {"fact_id": "fact-1", "match_any": ["利润保持稳定"]}
        ],
    }
    manifest = {
        "manifest_hash": "manifest-hash",
        "documents": [
            {
                "doc_id": "doc-a",
                "version": "v1",
                "content_hash": "content-hash",
            }
        ],
    }
    baseline = {
        "generation": {
            "provider": "deepseek",
            "model": "DeepSeek-V4.1-Flash",
            "model_revision": "frozen",
        },
        "repository": {"head_commit": "abc123"},
        "generation_config_sha256": "generation-hash",
        "prompts": {},
        "retrieval": {"embedding_revision": "embedding-v1"},
    }

    record = convert(envelope, case, manifest, baseline)

    assert record["verified_evidence"] == [
        {
            "evidence_id": "citation-evidence-1",
            "doc_id": "doc-a",
            "document_version": "v1",
            "content_hash": "content-hash",
            "locator": "doc-a_chunk_1",
            "excerpt": "利润保持稳定。",
            "source_method": "local_original_read",
            "supports_fact_ids": ["fact-1"],
            "conflict_status": "none",
        }
    ]
    assert record["retrieval_hits"][0]["chunk_id"] == "doc-a_chunk_1"
    assert record["citations"][0]["locator"] == "doc-a_chunk_1"
    assert record["citations"][0]["supports_claim"] is True


def test_parse_judge_json_accepts_fenced_json() -> None:
    value = parse_json(
        """```json
        {"judge_version":"judge.v1","correctness":5,"completeness":4,
        "faithfulness":5,"answer_relevance":4,"limitation_disclosure":3,
        "conflict_handling":5,"required_fact_ids_supported":["f1"],
        "unsupported_claim_ids":[],"rationale":"grounded"}
        ```"""
    )
    assert value["faithfulness"] == 5


def test_parse_judge_json_restores_runner_owned_version_metadata() -> None:
    value = parse_json(
        '{"correctness":5,"completeness":5,"faithfulness":5,'
        '"answer_relevance":5,"limitation_disclosure":4,"conflict_handling":5,'
        '"required_fact_ids_supported":[],"unsupported_claim_ids":[],'
        '"rationale":"grounded"}'
    )
    assert value["judge_version"] == "judge.v1"


def test_parse_judge_json_accepts_score_only_response_when_faithfulness_is_full() -> None:
    value = parse_json(
        '{"correctness":5,"completeness":5,"faithfulness":5,'
        '"answer_relevance":5,"limitation_disclosure":5,"conflict_handling":5}'
    )
    assert value["unsupported_claim_ids"] == []
    assert value["required_fact_ids_supported"] == []


def test_parse_judge_json_normalizes_kimi_nested_dimensions_conservatively() -> None:
    value = parse_json(
        '{"correctness":{"score":4,"rationale":"mostly correct"},'
        '"completeness":{"score":5,"justification":"complete"},'
        '"faithfulness":{"score":2,"rationale":"unsupported details"},'
        '"answer_relevance":{"score":5},'
        '"limitation_disclosure":{"score":1},'
        '"conflict_handling":{"score":5}}'
    )
    assert value["correctness"] == 4
    assert value["unsupported_claim_ids"] == ["judge-unspecified-unsupported-claim"]
    assert "mostly correct" in value["rationale"]


def test_parse_judge_json_normalizes_doubao_display_keys() -> None:
    value = parse_json(
        '{"Correctness":4,"Completeness":5,"Faithfulness":2,'
        '"Answer relevance":5,"Limitation disclosure":1,'
        '"Conflict handling":5}'
    )
    assert value["answer_relevance"] == 5
    assert value["unsupported_claim_ids"] == ["judge-unspecified-unsupported-claim"]
