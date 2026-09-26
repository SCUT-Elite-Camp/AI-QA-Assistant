from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from eval.wiki.ragas_evaluator import (
    RagasEvaluator,
    build_ragas_sample,
    id_context_scores,
    validate_evaluator_endpoint,
)


def test_external_evaluator_requires_explicit_authorization() -> None:
    assert (
        validate_evaluator_endpoint(
            "http://127.0.0.1:11434/v1/", allow_external=False
        )
        == "http://127.0.0.1:11434/v1"
    )
    with pytest.raises(ValueError, match="external Ragas evaluator is disabled"):
        validate_evaluator_endpoint("https://example.com/v1", allow_external=False)
    with pytest.raises(ValueError, match="must not be embedded"):
        validate_evaluator_endpoint(
            "http://user:secret@127.0.0.1:11434/v1", allow_external=False
        )
    assert (
        validate_evaluator_endpoint(
            "https://example.com/v1", allow_external=True
        )
        == "https://example.com/v1"
    )


def test_build_sample_keeps_evidence_ids_and_content_separate() -> None:
    sample = build_ragas_sample(
        {
            "query_id": "q-1",
            "retrieval_path": "wiki",
            "query": "Where is the fact?",
            "answer": "In section A.",
            "retrieved_evidence_ids": ["e-2", "e-1"],
            "retrieved_items": [
                {"evidence_id": "e-2", "content": "second"},
                {"evidence_id": "e-1", "content": "first"},
            ],
        },
        reference_answer="In section A.",
        reference_context_ids=["e-1"],
        evidence_content={"e-1": "first"},
    )
    assert sample["retrieved_context_ids"] == ["e-2", "e-1"]
    assert sample["retrieved_contexts"] == ["second", "first"]
    assert sample["reference_context_ids"] == ["e-1"]
    assert sample["reference_contexts"] == ["first"]
    assert sample["retrieval_path"] == "wiki"


def test_id_context_scores_are_deterministic_and_deduplicated() -> None:
    assert id_context_scores(["e-2", "e-1", "e-1"], ["e-1", "e-3"]) == {
        "ragas_id_context_precision": 0.5,
        "ragas_id_context_recall": 0.5,
    }


def test_ragas_metric_mapping_and_unsupported_claim_rate() -> None:
    class Metric:
        def __init__(self, value: float) -> None:
            self.value = value

        async def ascore(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(value=self.value)

    evaluator = object.__new__(RagasEvaluator)
    evaluator._metrics = {
        "ragas_context_precision": Metric(0.8),
        "ragas_context_recall": Metric(0.7),
        "answer_correctness": Metric(0.6),
        "faithfulness": Metric(0.75),
    }
    scores = asyncio.run(
        evaluator._ascore(
            {
                "user_input": "question",
                "retrieved_contexts": ["context"],
                "retrieved_context_ids": ["e-1", "e-2"],
                "reference_context_ids": ["e-1"],
                "response": "answer",
                "reference": "reference answer",
            }
        )
    )
    assert scores["answer_correctness"] == 0.6
    assert scores["faithfulness"] == 0.75
    assert scores["unsupported_claim_rate"] == 0.25
    assert scores["ragas_id_context_precision"] == 0.5
    assert scores["ragas_id_context_recall"] == 1.0
