import json
import logging
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class RetrievalError(Exception):
    """Raised when the retrieval tool cannot complete a search."""


class RetrievalParameterError(ValueError):
    """Raised when the caller passes invalid retrieval parameters."""


class SearchTool:
    """Agent-facing retrieval tool.

    CP2 keeps the public contract stable and implements vector, BM25, and
    hybrid retrieval behind the same entry point. The default backend is local
    and dependency-free; it can be replaced by Milvus later without changing the
    Agent call.
    """

    VALID_MODES = {"vector", "bm25", "hybrid"}

    def __init__(
        self,
        backend=None,
        chunks_path: str = "data/chunks.jsonl",
        documents_dir: str = "data/documents",
        logger: Optional[logging.Logger] = None,
    ):
        self.backend = backend or LocalJsonlSearchBackend(chunks_path=chunks_path)
        self.documents_dir = Path(documents_dir)
        self.logger = logger or logging.getLogger(__name__)

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        filters: Optional[Dict] = None,
        min_score: float = 0.0,
        trace_id: Optional[str] = None,
    ) -> List[Dict]:
        self._validate_params(query, top_k, mode, filters, min_score)

        started = time.perf_counter()
        trace = trace_id or "-"
        filters = filters or {}

        try:
            raw_results = self.backend.search(query.strip(), top_k=top_k, mode=mode, filters=filters)
            results = self._normalize_results(raw_results, filters=filters, min_score=float(min_score))
        except RetrievalParameterError:
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._log(trace, mode, top_k, 0, latency_ms)
            raise RetrievalError(f"retrieval_error: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._log(trace, mode, top_k, len(results), latency_ms)
        return results[:top_k]

    def _validate_params(
        self,
        query: str,
        top_k: int,
        mode: str,
        filters: Optional[Dict],
        min_score: float,
    ) -> None:
        if query is None or not str(query).strip():
            raise RetrievalParameterError("invalid_query: query must not be empty")

        if not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise RetrievalParameterError("invalid_top_k: top_k must be an integer from 1 to 20")

        if mode not in self.VALID_MODES:
            allowed = ", ".join(sorted(self.VALID_MODES))
            raise RetrievalParameterError(f"invalid_mode: mode must be one of {allowed}")

        if filters is not None and not isinstance(filters, dict):
            raise RetrievalParameterError("invalid_filters: filters must be a dict or None")

        try:
            float(min_score)
        except (TypeError, ValueError) as exc:
            raise RetrievalParameterError("invalid_min_score: min_score must be numeric") from exc

    def _normalize_results(self, raw_results: List[Dict], filters: Dict, min_score: float) -> List[Dict]:
        if not raw_results:
            return []

        scores = _normalize_scores([item.get("score", 0.0) for item in raw_results])
        normalized: List[Dict] = []

        for item, score in zip(raw_results, scores):
            doc_id = item.get("doc_id")
            chunk_index = item.get("chunk_index")
            chunk_text = item.get("chunk_text", item.get("text", ""))

            if doc_id is None or chunk_index is None:
                raise RetrievalError("retrieval_error: result missing doc_id or chunk_index")

            doc_id = str(doc_id)
            chunk_index = int(chunk_index)

            if not self._matches_filters(item, doc_id, filters):
                continue

            if float(score) < min_score:
                continue

            doc_meta = self._load_document_meta(doc_id)
            title = item.get("title") or doc_meta.get("title") or doc_id
            source_url = item.get("source_url") or doc_meta.get("source_url") or ""

            normalized.append(
                {
                    "doc_id": doc_id,
                    "chunk_id": item.get("chunk_id") or f"{doc_id}::chunk_{chunk_index}",
                    "chunk_index": chunk_index,
                    "chunk_text": str(chunk_text),
                    "title": str(title),
                    "score": float(score),
                    "vector_score": _safe_float(item.get("vector_score")),
                    "bm25_score": _safe_float(item.get("bm25_score")),
                    "source_url": str(source_url),
                }
            )

        normalized.sort(key=lambda row: row["score"], reverse=True)
        return normalized

    def _matches_filters(self, item: Dict, doc_id: str, filters: Dict) -> bool:
        if not filters:
            return True

        doc_ids = filters.get("doc_id") or filters.get("doc_ids")
        if doc_ids is not None:
            if isinstance(doc_ids, str):
                doc_ids = {doc_ids}
            else:
                doc_ids = set(doc_ids)
            if doc_id not in doc_ids:
                return False

        for key in ("space", "doc_type"):
            expected = filters.get(key)
            if expected is None:
                continue
            actual = item.get(key) or self._load_document_meta(doc_id).get(key)
            if actual != expected:
                return False

        return True

    def _load_document_meta(self, doc_id: str) -> Dict:
        path = self.documents_dir / f"{doc_id}.json"
        if not path.exists():
            return {}

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _log(self, trace_id: str, mode: str, top_k: int, results: int, latency_ms: int) -> None:
        self.logger.info(
            "[RETRIEVAL] trace_id=%s mode=%s top_k=%s results=%s latency=%sms",
            trace_id,
            mode,
            top_k,
            results,
            latency_ms,
        )


class LocalJsonlSearchBackend:
    """Dependency-free local retrieval backend for CP2.

    Vector mode uses TF-IDF cosine similarity. BM25 mode uses the standard BM25
    scoring formula. Hybrid mode fuses both rankings with RRF and deduplicates
    chunks by (doc_id, chunk_index).
    """

    def __init__(self, chunks_path: str, rrf_k: int = 60):
        self.chunks_path = Path(chunks_path)
        self.rrf_k = rrf_k
        self.chunks = self._load_chunks()
        self.tokenized_chunks = [_tokenize(self._chunk_text(chunk)) for chunk in self.chunks]
        self.doc_freq = self._build_doc_freq()
        self.avg_doc_len = self._average_doc_len()
        self.idf = self._build_idf()
        self.tfidf_vectors = [self._tfidf_vector(tokens) for tokens in self.tokenized_chunks]
        self.tfidf_norms = [_vector_norm(vec) for vec in self.tfidf_vectors]

    def search(self, query: str, top_k: int, mode: str, filters: Optional[Dict] = None) -> List[Dict]:
        if mode not in SearchTool.VALID_MODES:
            raise RetrievalParameterError(f"invalid_mode: {mode}")

        if not self.chunks:
            return []

        filters = filters or {}
        candidate_limit = max(top_k * 5, top_k, 20)

        if mode == "vector":
            return self._vector_search(query, candidate_limit, filters)[:top_k]
        if mode == "bm25":
            return self._bm25_search(query, candidate_limit, filters)[:top_k]
        return self._hybrid_search(query, candidate_limit, filters)[:top_k]

    def _load_chunks(self) -> List[Dict]:
        if not self.chunks_path.exists():
            return []

        chunks = []
        with self.chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))
        return chunks

    def _vector_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        query_tokens = _tokenize(query)
        query_vec = self._tfidf_vector(query_tokens)
        query_norm = _vector_norm(query_vec)

        rows = []
        for idx, chunk in enumerate(self.chunks):
            if not self._matches_filters(chunk, filters):
                continue

            score = _cosine(query_vec, query_norm, self.tfidf_vectors[idx], self.tfidf_norms[idx])
            if score <= 0:
                continue

            row = dict(chunk)
            row["score"] = score
            row["vector_score"] = score
            row["bm25_score"] = 0.0
            rows.append(row)

        rows.sort(key=lambda item: item["score"], reverse=True)
        return rows[:top_k]

    def _bm25_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        query_tokens = _tokenize(query)

        rows = []
        for idx, chunk in enumerate(self.chunks):
            if not self._matches_filters(chunk, filters):
                continue

            score = self._bm25_score(query_tokens, self.tokenized_chunks[idx])
            if score <= 0:
                continue

            row = dict(chunk)
            row["score"] = score
            row["vector_score"] = 0.0
            row["bm25_score"] = score
            rows.append(row)

        bm25_scores = _normalize_scores([row["bm25_score"] for row in rows])
        for row, score in zip(rows, bm25_scores):
            row["score"] = score
            row["bm25_score"] = score

        rows.sort(key=lambda item: item["score"], reverse=True)
        return rows[:top_k]

    def _hybrid_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        vector_rows = self._vector_search(query, top_k, filters)
        bm25_rows = self._bm25_search(query, top_k, filters)

        vector_rank = {_chunk_key(row): rank for rank, row in enumerate(vector_rows, start=1)}
        bm25_rank = {_chunk_key(row): rank for rank, row in enumerate(bm25_rows, start=1)}
        vector_scores = {_chunk_key(row): row["vector_score"] for row in vector_rows}
        bm25_scores = {_chunk_key(row): row["bm25_score"] for row in bm25_rows}

        merged: Dict[tuple, Dict] = {}

        for row in vector_rows + bm25_rows:
            key = _chunk_key(row)
            if key not in merged:
                merged[key] = dict(row)

            rrf_score = 0.0
            if key in vector_rank:
                rrf_score += 1.0 / (self.rrf_k + vector_rank[key])
            if key in bm25_rank:
                rrf_score += 1.0 / (self.rrf_k + bm25_rank[key])

            merged[key]["score"] = rrf_score
            merged[key]["vector_score"] = vector_scores.get(key, 0.0)
            merged[key]["bm25_score"] = bm25_scores.get(key, 0.0)

        rows = list(merged.values())
        rows.sort(key=lambda item: item["score"], reverse=True)

        final_scores = _normalize_scores([row["score"] for row in rows])
        for row, score in zip(rows, final_scores):
            row["score"] = score

        rows.sort(key=lambda item: item["score"], reverse=True)
        return rows[:top_k]

    def _build_doc_freq(self) -> Counter:
        doc_freq = Counter()
        for tokens in self.tokenized_chunks:
            doc_freq.update(set(tokens))
        return doc_freq

    def _average_doc_len(self) -> float:
        if not self.tokenized_chunks:
            return 0.0
        return sum(len(tokens) for tokens in self.tokenized_chunks) / len(self.tokenized_chunks)

    def _build_idf(self) -> Dict[str, float]:
        total_docs = max(len(self.tokenized_chunks), 1)
        return {
            token: math.log(1.0 + (total_docs - freq + 0.5) / (freq + 0.5))
            for token, freq in self.doc_freq.items()
        }

    def _tfidf_vector(self, tokens: List[str]) -> Dict[str, float]:
        counts = Counter(tokens)
        total = max(len(tokens), 1)
        return {token: (count / total) * self.idf.get(token, 0.0) for token, count in counts.items()}

    def _bm25_score(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0

        k1 = 1.5
        b = 0.75
        doc_len = len(doc_tokens)
        avg_len = self.avg_doc_len or 1.0
        tf = Counter(doc_tokens)

        score = 0.0
        for token in query_tokens:
            freq = tf.get(token, 0)
            if freq <= 0:
                continue
            idf = self.idf.get(token, 0.0)
            denom = freq + k1 * (1.0 - b + b * doc_len / avg_len)
            score += idf * (freq * (k1 + 1.0)) / denom
        return score

    def _matches_filters(self, chunk: Dict, filters: Dict) -> bool:
        if not filters:
            return True

        doc_ids = filters.get("doc_id") or filters.get("doc_ids")
        if doc_ids is not None:
            if isinstance(doc_ids, str):
                doc_ids = {doc_ids}
            else:
                doc_ids = set(doc_ids)
            if str(chunk.get("doc_id")) not in doc_ids:
                return False

        for key in ("space", "doc_type"):
            expected = filters.get(key)
            if expected is not None and chunk.get(key) != expected:
                return False

        return True

    def _chunk_text(self, chunk: Dict) -> str:
        return str(chunk.get("chunk_text", chunk.get("text", "")))


def _normalize_scores(scores: Iterable[float]) -> List[float]:
    values = []
    for score in scores:
        try:
            values.append(float(score))
        except (TypeError, ValueError):
            values.append(0.0)

    if not values:
        return []

    if all(0.0 <= score <= 1.0 for score in values):
        return values

    mn = min(values)
    mx = max(values)
    if abs(mx - mn) < 1e-12:
        return [1.0 if mx > 0 else 0.0 for _ in values]

    return [(score - mn) / (mx - mn) for score in values]


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tokenize(text: str) -> List[str]:
    text = str(text).lower()
    word_tokens = re.findall(r"[a-z0-9_]+", text)
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]", text)
    return word_tokens + cjk_tokens


def _vector_norm(vector: Dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _cosine(
    left: Dict[str, float],
    left_norm: float,
    right: Dict[str, float],
    right_norm: float,
) -> float:
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    return dot / (left_norm * right_norm)


def _chunk_key(row: Dict) -> tuple:
    return (str(row.get("doc_id")), int(row.get("chunk_index", 0)))
