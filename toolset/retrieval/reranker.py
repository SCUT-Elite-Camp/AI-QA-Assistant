import math
from typing import Any, Dict, List, Optional


DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_RERANK_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"


class CrossEncoderReranker:
    """Lazily load a pinned Cross-Encoder and reorder retrieval candidates."""

    def __init__(
        self,
        model_id: str = DEFAULT_RERANK_MODEL,
        revision: str = DEFAULT_RERANK_REVISION,
        max_length: int = 512,
        batch_size: int = 32,
        device: str = "cpu",
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.max_length = max_length
        self.batch_size = batch_size
        self.device = device
        self._model: Optional[Any] = None

    @property
    def model(self) -> Any:
        if self._model is None:
            import os
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"] = "1"
            from sentence_transformers import CrossEncoder

            try:
                self._model = CrossEncoder(
                    self.model_id,
                    revision=self.revision,
                    max_length=self.max_length,
                    device=self.device,
                    local_files_only=True,
                )
            except Exception:
                # If pinned revision is not local, try local loading without revision
                self._model = CrossEncoder(
                    self.model_id,
                    max_length=self.max_length,
                    device=self.device,
                    local_files_only=True,
                )
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        """Rerank a candidate prefix and preserve the remaining retrieval order."""
        if not candidates:
            return []

        limit = min(max(int(top_n), 1), len(candidates))
        prefix = candidates[:limit]
        pairs = [(query, str(item.get("chunk_text", ""))) for item in prefix]
        raw_scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        if len(raw_scores) != limit:
            raise RuntimeError(
                f"reranker_score_count_mismatch: expected {limit}, got {len(raw_scores)}"
            )

        scored = []
        for item, raw_score in zip(prefix, raw_scores):
            logit = float(raw_score)
            row = dict(item)
            row["retrieval_score"] = float(item.get("score", 0.0))
            row["rerank_score"] = _sigmoid(logit)
            row["score"] = row["rerank_score"]
            scored.append(row)

        scored.sort(key=lambda item: item["rerank_score"], reverse=True)
        return scored + candidates[limit:]


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)
