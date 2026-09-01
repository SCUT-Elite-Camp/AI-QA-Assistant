import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.query import HybridIntentRouter, IntentResult, QueryIntent
from agent.query import QueryUnderstanding
from agent.query.hybrid_intent import (
    SentenceTransformerIntentEncoder,
    _load_local_sentence_transformer,
)


pytestmark = pytest.mark.no_storage


class FakeEncoder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self.vectors[text] for text in texts]


class FakeVector(list):
    def tolist(self) -> list[float]:
        return list(self)


def _fallback(intent: QueryIntent = QueryIntent.KNOWLEDGE_QA) -> Mock:
    fallback = Mock()
    fallback.classify.return_value = IntentResult(
        intent=intent,
        confidence=0.8,
        reason="llm fallback",
    )
    return fallback


def test_high_precision_rule_skips_embedding_and_llm() -> None:
    fallback = _fallback()
    encoder = FakeEncoder({})
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        enabled=True,
    )

    result = router.classify("比较 ToolExecutor 和 Evidence Gate 的区别", [])

    assert result.intent == QueryIntent.COMPARISON
    assert result.confidence == 1.0
    assert encoder.calls == []
    fallback.classify.assert_not_called()


def test_high_confidence_embedding_prediction_skips_llm() -> None:
    examples = {
        QueryIntent.KNOWLEDGE_QA: ["knowledge example"],
        QueryIntent.SYSTEM_HELP: ["help example"],
    }
    encoder = FakeEncoder(
        {
            "knowledge example": [1.0, 0.0],
            "help example": [0.0, 1.0],
            "target query": [0.99, 0.01],
        }
    )
    fallback = _fallback(QueryIntent.SYSTEM_HELP)
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        examples=examples,
        enabled=True,
        threshold=0.7,
        margin=0.1,
    )

    result = router.classify("target query", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.confidence > 0.99
    fallback.classify.assert_not_called()


def test_low_margin_embedding_prediction_falls_back_to_llm() -> None:
    examples = {
        QueryIntent.KNOWLEDGE_QA: ["knowledge example"],
        QueryIntent.SYSTEM_HELP: ["help example"],
    }
    encoder = FakeEncoder(
        {
            "knowledge example": [1.0, 0.0],
            "help example": [0.0, 1.0],
            "uncertain query": [1.0, 1.0],
        }
    )
    fallback = _fallback(QueryIntent.SYSTEM_HELP)
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        examples=examples,
        enabled=True,
        threshold=0.7,
        margin=0.1,
    )

    result = router.classify("uncertain query", [])

    assert result.intent == QueryIntent.SYSTEM_HELP
    fallback.classify.assert_called_once()


def test_history_always_uses_llm_to_preserve_follow_up_flags() -> None:
    fallback = _fallback()
    encoder = FakeEncoder({})
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        enabled=True,
    )
    history = [{"role": "user", "content": "介绍 ToolRegistry"}]

    router.classify("它有什么作用？", history)

    assert encoder.calls == []
    fallback.classify.assert_called_once_with("它有什么作用？", history)


def test_embedding_error_falls_back_to_llm() -> None:
    fallback = _fallback(QueryIntent.DOCUMENT_SEARCH)
    encoder = Mock()
    encoder.encode.side_effect = RuntimeError("model unavailable")
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        examples={QueryIntent.KNOWLEDGE_QA: ["example"]},
        enabled=True,
    )

    result = router.classify("find something", [])

    assert result.intent == QueryIntent.DOCUMENT_SEARCH
    fallback.classify.assert_called_once()


def test_local_sentence_transformer_weights_are_shared_per_process(
    monkeypatch,
    tmp_path,
) -> None:
    model = Mock()
    model.encode.return_value = [FakeVector([1.0, 0.0])]
    constructor = Mock(return_value=model)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=constructor),
    )
    _load_local_sentence_transformer.cache_clear()

    first = SentenceTransformerIntentEncoder(str(tmp_path))
    second = SentenceTransformerIntentEncoder(str(tmp_path))

    assert first.encode(["first"]) == [[1.0, 0.0]]
    assert second.encode(["second"]) == [[1.0, 0.0]]
    constructor.assert_called_once_with(str(tmp_path.resolve()), local_files_only=True)
    assert first._model is second._model
    _load_local_sentence_transformer.cache_clear()


def test_query_understanding_uses_hybrid_router_by_default() -> None:
    service = QueryUnderstanding()

    assert isinstance(service.intent_classifier, HybridIntentRouter)


def test_default_intent_examples_include_english_knowledge_queries() -> None:
    examples = HybridIntentRouter._load_examples()

    assert any("QueryPlan" in value for value in examples[QueryIntent.KNOWLEDGE_QA])
    assert any("CitationChecker" in value for value in examples[QueryIntent.KNOWLEDGE_QA])
    assert any("Compare" in value for value in examples[QueryIntent.COMPARISON])


def test_local_only_classification_never_calls_llm_fallback() -> None:
    fallback = _fallback(QueryIntent.SYSTEM_HELP)
    encoder = FakeEncoder(
        {
            "knowledge example": [1.0, 0.0],
            "uncertain query": [0.7, 0.7],
        }
    )
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        examples={QueryIntent.KNOWLEDGE_QA: ["knowledge example"]},
        enabled=True,
        threshold=1.1,
        margin=1.0,
    )

    result = router.classify_local(
        "uncertain query",
        default_intent=QueryIntent.SUMMARIZATION,
    )

    assert result.intent == QueryIntent.SUMMARIZATION
    assert result.reason == "local_only_parent_intent_fallback"
    fallback.classify.assert_not_called()


def test_local_batch_encodes_all_unresolved_queries_together() -> None:
    fallback = _fallback(QueryIntent.SYSTEM_HELP)
    encoder = FakeEncoder(
        {
            "knowledge example": [1.0, 0.0],
            "first task": [1.0, 0.0],
            "second task": [1.0, 0.0],
        }
    )
    router = HybridIntentRouter(
        fallback=fallback,
        encoder=encoder,
        examples={QueryIntent.KNOWLEDGE_QA: ["knowledge example"]},
        enabled=True,
        threshold=0.7,
        margin=0.0,
    )

    results = router.classify_local_batch(["first task", "second task"])

    assert [result.intent for result in results] == [
        QueryIntent.KNOWLEDGE_QA,
        QueryIntent.KNOWLEDGE_QA,
    ]
    assert encoder.calls[-1] == ["first task", "second task"]
    fallback.classify.assert_not_called()
