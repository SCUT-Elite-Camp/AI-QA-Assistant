"""Shared local query/passage ranking. Scores are relevance logits, not truth probabilities."""
from __future__ import annotations

import logging
import math
import os
import threading
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

LOGGER = logging.getLogger(__name__)
_INFERENCE_LOCK = threading.Lock()
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
BEFORE_RERANK = ContextVar('before_semantic_rerank', default=None)


def enabled() -> bool:
    return os.getenv("RERANK_ENABLED", "true").lower() in {"1", "true", "yes"}


def candidate_count(top_k: int) -> int:
    return max(top_k, min(100, max(20, int(os.getenv("RERANK_CANDIDATE_K", "20")))))


def model_path() -> Path:
    return Path(os.getenv("RERANK_MODEL_PATH", str(
        Path(__file__).resolve().parents[2] / "data-persistence/models/ms-marco-MiniLM-L6-v2"
    )))


@lru_cache(maxsize=2)
def _load_model(path: str, device: str):
    # Request handling never downloads weights or executes remote model code.
    if not Path(path).is_dir():
        raise RuntimeError("reranker_model_not_installed")
    if device == 'cpu':
        import torch
        # Configure once, not per request. PyTorch's CPU thread limit also
        # applies to other local Torch models in this service process.
        torch.set_num_threads(max(1, min(32, int(os.getenv('RERANK_CPU_THREADS', '4')))))
    from sentence_transformers import CrossEncoder
    return CrossEncoder(path, device=device, max_length=512, local_files_only=True,
                        trust_remote_code=False)


def rerank(query: str, rows: list[dict], top_k: int, *, text_key: str = "chunk_text",
           predictor=None) -> list[dict]:
    """Rank already scoped candidates; preserve evidence text, hashes and retrieval scores.

    Duplicate views are suppressed only within the same source location.
    Identical values in different rows/sections keep their distinct ownership.
    """
    if not enabled():
        return rows[:top_k]
    unique, seen = [], set()
    for row in rows:
        locator = row.get('locator') or {}
        identity = (row.get("doc_id", row.get("attachment_id")), row.get("version_id"),
                    " ".join(str(row.get(text_key) or "").split()),
                    tuple(row.get('section_path') or locator.get('section_path') or []),
                    tuple(locator.get(key) for key in ('block', 'block_start', 'block_end', 'row_start', 'row_end')))
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(dict(row))
    candidates = unique[:candidate_count(top_k)]
    if not candidates:
        return []
    check = BEFORE_RERANK.get()
    if check is not None:
        # Authorization/version failures must escape, never become a ranking
        # fallback that could continue with revoked source material.
        check(candidates)
    try:
        pairs = [(query, "\n".join(filter(None, [str(row.get("title") or row.get("filename") or ""),
                  " > ".join(row.get("section_path") or []),
                  str(row.get("index_text") or row.get(text_key) or "")]))) for row in candidates]
        if predictor is None:
            model = _load_model(str(model_path()), os.getenv("RERANK_DEVICE", "cpu"))
            for row, (question, passage) in zip(candidates, pairs):
                length = len(model.tokenizer(question, passage, truncation=False)['input_ids'])
                row['rerank_input_tokens'] = length
                row['rerank_truncated'] = length > 512
            if any(row['rerank_truncated'] for row in candidates):
                LOGGER.warning('RERANK_INPUT_TRUNCATED candidates=%d',
                               sum(row['rerank_truncated'] for row in candidates))
            with _INFERENCE_LOCK:
                scores = model.predict(pairs, batch_size=8, show_progress_bar=False)
        else:
            scores = predictor(pairs)
        scores = [float(score) for score in scores]
        if len(scores) != len(candidates) or not all(math.isfinite(s) for s in scores):
            raise ValueError("invalid_reranker_scores")
        for rank, (row, score) in enumerate(zip(candidates, scores), 1):
            row.update(retrieval_score=row.get("score"), rerank_score=score,
                       retrieval_rank=rank, rerank_status="completed")
        candidates.sort(key=lambda row: (-row["rerank_score"], row["retrieval_rank"]))
        for rank, row in enumerate(candidates, 1):
            row["rerank_rank"] = rank
        LOGGER.info('RERANK_COMPLETED candidates=%d results=%d model=%s', len(candidates), min(top_k, len(candidates)), MODEL_ID)
        return candidates[:top_k]
    except Exception as exc:
        LOGGER.warning("RERANK_DEGRADED reason=%s candidates=%d", type(exc).__name__, len(candidates))
        return [{**row, "rerank_status": "degraded", "rerank_error": type(exc).__name__}
                for row in candidates[:top_k]]
