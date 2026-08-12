import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from agent.config.settings import settings
from agent.query.intent_classifier import IntentClassifier
from agent.query.schemas import IntentResult
from agent.schemas.query_plan import QueryIntent


class TextEncoder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


@lru_cache(maxsize=4)
def _load_local_sentence_transformer(model_path: str):
    """Load local weights once per worker process and share the read-only model."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_path, local_files_only=True)


class SentenceTransformerIntentEncoder:
    """Lazy local encoder; never downloads a model implicitly."""

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path.strip()
        self._model = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not self.model_path:
            raise RuntimeError("INTENT_EMBEDDING_MODEL_PATH is not configured")
        path = Path(self.model_path)
        if not path.exists():
            raise RuntimeError(f"intent embedding model path does not exist: {path}")
        if self._model is None:
            self._model = _load_local_sentence_transformer(str(path.resolve()))
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]


class HybridIntentRouter:
    """Rules, embedding prototypes, then the existing LLM classifier."""

    _RULES = (
        (QueryIntent.UNSUPPORTED, re.compile(r"转账|修改.*余额|删除.*用户|绕过.*权限|登录.*账户")),
        (QueryIntent.COMPARISON, re.compile(r"比较|对比|区别|差异|分别|各自|优缺点")),
        (QueryIntent.SUMMARIZATION, re.compile(r"总结|概括|摘要|归纳")),
        (QueryIntent.DOCUMENT_SEARCH, re.compile(r"(?:查找|搜索|列出|找到).*(?:文档|文件|资料)|知识库里有哪些.*文档")),
        (QueryIntent.SYSTEM_HELP, re.compile(r"系统.*(?:怎么用|如何使用|支持哪些能力)|如何查看.*引用|可以上传.*文件")),
        (QueryIntent.CASUAL_CHAT, re.compile(r"^(?:你好|您好|早上好|下午好|晚上好|谢谢|感谢|很高兴认识你)[！!。.]?$")),
    )

    def __init__(
        self,
        fallback: IntentClassifier | None = None,
        *,
        encoder: TextEncoder | None = None,
        examples: dict[QueryIntent, list[str]] | None = None,
        enabled: bool | None = None,
        threshold: float | None = None,
        margin: float | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.fallback = fallback or IntentClassifier()
        self.enabled = (
            settings.HYBRID_INTENT_ROUTER_ENABLED if enabled is None else enabled
        )
        self.threshold = (
            settings.INTENT_EMBEDDING_THRESHOLD if threshold is None else threshold
        )
        self.margin = settings.INTENT_EMBEDDING_MARGIN if margin is None else margin
        self.encoder = encoder or SentenceTransformerIntentEncoder(
            settings.INTENT_EMBEDDING_MODEL_PATH
        )
        self.examples = examples or self._load_examples()
        self.logger = logger or logging.getLogger("agent-layer.query")
        self._example_vectors: list[list[float]] | None = None
        self._example_labels: list[QueryIntent] = []

    def classify(self, query: str, history: list[dict]) -> IntentResult:
        normalized = query.strip()
        if not self.enabled or self._has_history(history):
            return self.fallback.classify(query, history)

        rule_intent = self._rule_intent(normalized)
        if rule_intent is not None:
            self.logger.info(
                "[HYBRID_INTENT] source=rule intent=%s query=%s",
                rule_intent,
                normalized,
            )
            return IntentResult(
                intent=rule_intent,
                confidence=1.0,
                reason="high_precision_rule",
            )

        try:
            prediction = self._embedding_intent(normalized)
        except Exception as exc:
            self.logger.warning(
                "[HYBRID_INTENT] source=embedding action=fallback error=%s query=%s",
                exc.__class__.__name__,
                normalized,
            )
            return self.fallback.classify(query, history)

        if prediction is None:
            return self.fallback.classify(query, history)
        intent, score, score_margin = prediction
        self.logger.info(
            "[HYBRID_INTENT] source=embedding intent=%s score=%.3f margin=%.3f query=%s",
            intent,
            score,
            score_margin,
            normalized,
        )
        return IntentResult(
            intent=intent,
            confidence=max(0.0, min(1.0, score)),
            reason=f"embedding score={score:.3f} margin={score_margin:.3f}",
        )

    def warmup(self) -> None:
        """Load the local encoder and cache prototype vectors."""
        if self.enabled:
            self._ensure_example_vectors()

    def classify_local(
        self,
        query: str,
        *,
        default_intent: QueryIntent = QueryIntent.KNOWLEDGE_QA,
    ) -> IntentResult:
        """Classify without ever delegating to the online LLM fallback."""
        normalized = query.strip()
        rule_intent = self._rule_intent(normalized) if self.enabled else None
        if rule_intent is not None:
            return IntentResult(
                intent=rule_intent,
                confidence=1.0,
                reason="high_precision_rule_local_only",
            )
        if self.enabled:
            try:
                prediction = self._embedding_intent(normalized)
            except Exception as exc:
                self.logger.warning(
                    "[HYBRID_INTENT] source=embedding action=local_default "
                    "error=%s query=%s",
                    exc.__class__.__name__,
                    normalized,
                )
            else:
                if prediction is not None:
                    intent, score, score_margin = prediction
                    return IntentResult(
                        intent=intent,
                        confidence=max(0.0, min(1.0, score)),
                        reason=(
                            f"embedding_local_only score={score:.3f} "
                            f"margin={score_margin:.3f}"
                        ),
                    )
        return IntentResult(
            intent=default_intent,
            confidence=0.5,
            reason="local_only_parent_intent_fallback",
        )

    def classify_local_batch(
        self,
        queries: list[str],
        *,
        default_intent: QueryIntent = QueryIntent.KNOWLEDGE_QA,
    ) -> list[IntentResult]:
        """Classify sub-queries in one local embedding batch, without online I/O."""
        results: list[IntentResult | None] = [None] * len(queries)
        pending_indexes: list[int] = []
        pending_queries: list[str] = []
        for index, query in enumerate(queries):
            normalized = query.strip()
            rule_intent = self._rule_intent(normalized) if self.enabled else None
            if rule_intent is not None:
                results[index] = IntentResult(
                    intent=rule_intent,
                    confidence=1.0,
                    reason="high_precision_rule_local_only",
                )
            else:
                pending_indexes.append(index)
                pending_queries.append(normalized)

        predictions: list[tuple[QueryIntent, float, float] | None] = []
        if pending_queries and self.enabled:
            try:
                self._ensure_example_vectors()
                predictions = [
                    self._prediction_from_vector(vector)
                    for vector in self.encoder.encode(pending_queries)
                ]
            except Exception as exc:
                self.logger.warning(
                    "[HYBRID_INTENT] source=embedding_batch action=local_default "
                    "error=%s count=%d",
                    exc.__class__.__name__,
                    len(pending_queries),
                )
                predictions = [None] * len(pending_queries)
        else:
            predictions = [None] * len(pending_queries)

        for index, prediction in zip(pending_indexes, predictions):
            if prediction is None:
                results[index] = IntentResult(
                    intent=default_intent,
                    confidence=0.5,
                    reason="local_only_parent_intent_fallback",
                )
                continue
            intent, score, score_margin = prediction
            results[index] = IntentResult(
                intent=intent,
                confidence=max(0.0, min(1.0, score)),
                reason=(
                    f"embedding_batch_local_only score={score:.3f} "
                    f"margin={score_margin:.3f}"
                ),
            )
        return [
            result
            if result is not None
            else IntentResult(
                intent=default_intent,
                confidence=0.5,
                reason="local_only_parent_intent_fallback",
            )
            for result in results
        ]

    def _embedding_intent(
        self,
        query: str,
    ) -> tuple[QueryIntent, float, float] | None:
        self._ensure_example_vectors()
        query_vector = self.encoder.encode([query])[0]
        return self._prediction_from_vector(query_vector)

    def _prediction_from_vector(
        self,
        query_vector: list[float],
    ) -> tuple[QueryIntent, float, float] | None:
        best_by_intent: dict[QueryIntent, float] = {}
        for label, vector in zip(self._example_labels, self._example_vectors or []):
            score = self._cosine(query_vector, vector)
            best_by_intent[label] = max(best_by_intent.get(label, -1.0), score)
        ranked = sorted(best_by_intent.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None
        top_intent, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else -1.0
        score_margin = top_score - second_score
        if top_score < self.threshold or score_margin < self.margin:
            return None
        return top_intent, top_score, score_margin

    def _ensure_example_vectors(self) -> None:
        if self._example_vectors is not None:
            return
        texts: list[str] = []
        labels: list[QueryIntent] = []
        for intent, examples in self.examples.items():
            for example in examples:
                if example.strip():
                    texts.append(example.strip())
                    labels.append(intent)
        self._example_vectors = self.encoder.encode(texts)
        self._example_labels = labels

    @classmethod
    def _rule_intent(cls, query: str) -> QueryIntent | None:
        for intent, pattern in cls._RULES:
            if pattern.search(query):
                return intent
        return None

    @staticmethod
    def _has_history(history: list[dict]) -> bool:
        return any(
            isinstance(item, dict)
            and isinstance(item.get("content"), str)
            and item["content"].strip()
            for item in history
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("embedding dimensions do not match")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _load_examples() -> dict[QueryIntent, list[str]]:
        path = Path(__file__).with_name("intent_examples.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            QueryIntent(key): [str(value) for value in values]
            for key, values in payload.items()
        }
