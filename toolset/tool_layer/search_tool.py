import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from retrieval.orchestrator import default_observation
from tool_layer.base_tool import BaseTool


logging.getLogger(__name__).addHandler(logging.NullHandler())


class RetrievalError(Exception):
    """Raised when the retrieval tool cannot complete a search."""
    pass


class RetrievalParameterError(ValueError):
    """Raised when the caller passes invalid retrieval parameters."""
    pass


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


def _chunk_key(row: Dict) -> tuple:
    return (str(row.get("doc_id")), int(row.get("chunk_index", 0)))


def _matches_filters(item: Dict, filters: Dict, doc_meta: Optional[Dict] = None) -> bool:
    if not filters:
        return True

    doc_id = str(item.get("doc_id", ""))
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
        actual = item.get(key) or (doc_meta.get(key) if doc_meta else None)
        if actual != expected:
            return False

    return True


def _hybrid_search(
    vector_rows: list[dict],
    bm25_rows: list[dict],
    top_k: int,
    rrf_k: int = 60,
) -> list[dict]:
    vector_rank = {_chunk_key(row): rank for rank, row in enumerate(vector_rows, start=1)}
    bm25_rank = {_chunk_key(row): rank for rank, row in enumerate(bm25_rows, start=1)}
    vector_scores = {_chunk_key(row): row["vector_score"] for row in vector_rows}
    bm25_scores = {_chunk_key(row): row["bm25_score"] for row in bm25_rows}

    merged = {}
    for row in vector_rows + bm25_rows:
        key = _chunk_key(row)
        if key not in merged:
            merged[key] = dict(row)

        rrf_score = 0.0
        if key in vector_rank:
            rrf_score += 1.0 / (rrf_k + vector_rank[key])
        if key in bm25_rank:
            rrf_score += 1.0 / (rrf_k + bm25_rank[key])

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


class SearchTool(BaseTool):
    """Agent-facing retrieval tool."""

    VALID_MODES = {"vector", "bm25", "hybrid"}
    def __init__(
        self,
        backend=None,
        documents_dir: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        min_score: float = 0.0,
        rrf_k: int = 60,
        reranker=None,
        rerank_top_n: int = 20,
        rerank_modes: Optional[Iterable[str]] = None,
        rerank_fail_open: bool = True,
        retrieval_orchestrator=None,
        backend_timeout_seconds: float = 2.0,
    ):
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.documents_dir = (
            Path(documents_dir) if documents_dir else
            self.project_root / "data-persistence" / "data" / "documents"
        )
        self.bm25_path = self.project_root / "data-persistence" / "data" / "bm25_index.pkl"

        self.backend = backend
        self.logger = logger or logging.getLogger(__name__)
        self.latest_results = []
        self.min_score = min_score
        self.rrf_k = rrf_k
        self.reranker = reranker
        self.rerank_top_n = rerank_top_n
        if isinstance(rerank_modes, str):
            rerank_modes = {rerank_modes}
        self.rerank_modes = frozenset(rerank_modes or {"hybrid"})
        self.rerank_fail_open = rerank_fail_open
        self.retrieval_orchestrator = retrieval_orchestrator
        self.backend_timeout_seconds = float(backend_timeout_seconds)

        self._milvus_store = None
        self._bm25_index = None

    @property
    def milvus_store(self):
        if self._milvus_store is None:
            from storage.milvus_store import MilvusStore
            self._milvus_store = MilvusStore()
        return self._milvus_store

    @property
    def bm25_index(self):
        if self._bm25_index is None:
            from retrieval.bm25_index import BM25Index
            if self.bm25_path.exists():
                self._bm25_index = BM25Index.load_from_file(str(self.bm25_path))
            else:
                self._bm25_index = BM25Index()
        return self._bm25_index

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return (
            "Search the document database for information matching the query. "
            "Use this tool when you need to answer questions about regulations, "
            "rules, project structures, or work divisions."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query keywords or question."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of document chunks to retrieve (1-20).",
                    "default": 5
                },
                "mode": {
                    "type": "string",
                    "description": "Retrieval mode: 'vector', 'bm25', or 'hybrid'.",
                    "default": "hybrid"
                }
            },
            "required": ["query"]
        }

    def execute(self, **kwargs: Any) -> Any:
        query = kwargs.get("query")
        top_k = kwargs.get("top_k", 5)
        mode = kwargs.get("mode", "hybrid")

        results = self.search(
            query=query,
            top_k=top_k,
            mode=mode,
            min_score=self.min_score,
            topic_doc_ids=getattr(self, "topic_doc_ids", None),
            weight_mode=getattr(self, "weight_mode", "auto"),
            consecutive_no_new_docs_count=getattr(self, "consecutive_no_new_docs_count", 0),
        )
        self.latest_results = results

        if not results:
            return "No relevant documents found."

        blocks = []
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"[{index}] title: {item.get('title')}\n"
                f"doc_id: {item.get('doc_id')}\n"
                f"chunk_id: {item.get('chunk_id')}\n"
                f"content: {item.get('chunk_text')}\n"
                f"score: {item.get('score'):.4f}"
            )
        return "\n\n".join(blocks)


    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        filters: Optional[Dict] = None,
        min_score: float = 0.0,
        trace_id: Optional[str] = None,
        topic_doc_ids: Optional[List[str]] = None,
        topic_titles: Optional[List[str]] = None,
        weight_mode: str = "auto",
        consecutive_no_new_docs_count: int = 0,
    ) -> List[Dict]:
        self._validate_params(query, top_k, mode, filters, min_score)
        started = time.perf_counter()
        trace = trace_id or "-"
        filters = filters or {}

        try:
            normalized_query = query.strip()
            use_reranker = self.reranker is not None and mode in self.rerank_modes
            candidate_limit = (
                self.retrieval_orchestrator.config.fusion_candidate_limit
                if self.retrieval_orchestrator is not None
                else 100
            )
            candidate_k = min(
                candidate_limit,
                max(top_k * 3, self.rerank_top_n) if use_reranker else top_k * 3,
            )
            observation = default_observation(mode)
            if self.retrieval_orchestrator is None:
                raw_results = self._search_internal(
                    normalized_query, candidate_k, mode, filters
                )
            else:
                raw_results, observation = self.retrieval_orchestrator.search(
                    query=normalized_query,
                    candidate_k=candidate_k,
                    requested_top_k=top_k,
                    mode=mode,
                    filters=filters,
                    started=started,
                    trace_id=trace,
                    channel_search=self._search_channel,
                )
            results = self._normalize_results(
                raw_results, filters, float(min_score)
            )
            if use_reranker and results:
                results = self._rerank(normalized_query, results, trace)

            if results and (topic_doc_ids or topic_titles):
                results = self._apply_topic_weighting(
                    results=results,
                    top_k=top_k,
                    topic_doc_ids=topic_doc_ids,
                    topic_titles=topic_titles,
                    weight_mode=weight_mode,
                    consecutive_no_new_docs_count=consecutive_no_new_docs_count,
                )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._log(
                trace, mode, top_k, 0, latency_ms, [],
                locals().get("observation", default_observation(mode)),
                normalized_query if "normalized_query" in locals() else str(query),
            )
            self.logger.error(
                "[RETRIEVAL_ERROR] trace_id=%s mode=%s error=%s",
                trace,
                mode,
                exc,
            )
            if isinstance(exc, RetrievalParameterError):
                raise
            raise RetrievalError(f"retrieval_error: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        results = results[:top_k]
        top_scores = [row["score"] for row in results[:5]]
        observation["rerank_used"] = bool(use_reranker and results)
        self._log(
            trace, mode, top_k, len(results), latency_ms, top_scores,
            observation, normalized_query,
        )
        return results

    def _apply_topic_weighting(
        self,
        results: List[Dict],
        top_k: int,
        topic_doc_ids: Optional[List[str]] = None,
        topic_titles: Optional[List[str]] = None,
        weight_mode: str = "auto",
        consecutive_no_new_docs_count: int = 0,
    ) -> List[Dict]:
        import math
        if not results or (not topic_doc_ids and not topic_titles):
            return results[:top_k]

        # Rule 3: consecutive >= 3 no new docs -> fallback boost factor to 1.0
        if consecutive_no_new_docs_count >= 3:
            boost_multiplier = 1.0
        elif weight_mode == "deeper":
            boost_multiplier = 1.5
        elif weight_mode == "wider":
            boost_multiplier = 1.0
        else: # "auto"
            boost_multiplier = 1.2

        # Build normalized lookup sets for SAME DOCUMENT matching
        topic_doc_set = {str(x).strip().lower() for x in (topic_doc_ids or []) if str(x).strip()}
        topic_titles_set = {str(x).strip().lower() for x in (topic_titles or []) if str(x).strip()}

        def is_same_document(item: dict) -> bool:
            item_doc_id = str(item.get("doc_id", "")).strip().lower()
            item_title = str(item.get("title", "")).strip().lower()
            item_source = str(item.get("source_url", "")).strip().lower()

            if item_doc_id in topic_doc_set or item_doc_id in topic_titles_set:
                return True
            if item_title in topic_titles_set or item_title in topic_doc_set:
                return True
            if item_source in topic_doc_set or item_source in topic_titles_set:
                return True

            # Matching by clean filename / title substring for the SAME DOCUMENT
            all_known = topic_doc_set.union(topic_titles_set)
            for target in all_known:
                if target and len(target) >= 3:
                    if target in item_title or item_title in target or target in item_doc_id:
                        return True
            return False

        scored_results = []
        for item in results:
            base_score = float(item.get("score", 0.0))
            is_in_pool = is_same_document(item)
            weighted_score = base_score * boost_multiplier if is_in_pool else base_score
            scored_results.append({
                **item,
                "_weighted_score": weighted_score,
                "_is_in_pool": is_in_pool
            })

        scored_results.sort(key=lambda x: x["_weighted_score"], reverse=True)

        # Rule 2: Force at least 30% of top_k results to be non-pool documents (if available)
        non_pool_quota = max(1, math.ceil(top_k * 0.30)) if len(scored_results) >= top_k else 0
        non_pool_items = [r for r in scored_results if not r["_is_in_pool"]]
        
        selected_non_pool = non_pool_items[:non_pool_quota]
        selected_non_pool_ids = {r.get("chunk_id") for r in selected_non_pool}

        remaining_candidates = [r for r in scored_results if r.get("chunk_id") not in selected_non_pool_ids]
        needed_remaining = top_k - len(selected_non_pool)
        final_selected = selected_non_pool + remaining_candidates[:needed_remaining]

        final_selected.sort(key=lambda x: x["_weighted_score"], reverse=True)
        
        clean_results = []
        for item in final_selected:
            res = dict(item)
            res["score"] = res.pop("_weighted_score", res.get("score"))
            res.pop("_is_in_pool", None)
            clean_results.append(res)

        return clean_results[:top_k]


    def _search_channel(
        self,
        query: str,
        top_k: int,
        retriever: str,
        filters: Dict,
    ) -> List[Dict]:
        if self.backend is not None:
            return self.backend.search(
                query, top_k=top_k, mode=retriever, filters=filters
            )
        candidate_limit = max(top_k * 5, 20)
        if retriever == "vector":
            return self._vector_search(query, candidate_limit, filters)[:top_k]
        if retriever == "bm25":
            return self._bm25_search(query, candidate_limit, filters)[:top_k]
        raise RetrievalParameterError(f"invalid_retriever: {retriever}")

    def _rerank(self, query: str, results: List[Dict], trace_id: str) -> List[Dict]:
        try:
            return self.reranker.rerank(query, results, self.rerank_top_n)
        except Exception as exc:
            if not self.rerank_fail_open:
                raise
            self.logger.warning(
                "[RERANK_FALLBACK] trace_id=%s model=%s error=%s",
                trace_id,
                getattr(self.reranker, "model_id", type(self.reranker).__name__),
                exc,
            )
            return results

    def _search_internal(self, query: str, top_k: int, mode: str, filters: Dict) -> List[Dict]:
        if self.backend is not None:
            return self.backend.search(query, top_k=top_k, mode=mode, filters=filters)

        candidate_limit = max(top_k * 5, 20)
        if mode == "vector":
            return self._vector_search(query, candidate_limit, filters)[:top_k]
        if mode == "bm25":
            return self._bm25_search(query, candidate_limit, filters)[:top_k]

        vector_rows = self._vector_search(query, candidate_limit, filters)
        bm25_rows = self._bm25_search(query, candidate_limit, filters)
        return _hybrid_search(vector_rows, bm25_rows, top_k, self.rrf_k)

    def _vector_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        from pipeline.embedder import embed_texts

        query_vector = embed_texts([query])[0]

        doc_ids_filter = None
        doc_ids = filters.get("doc_id") or filters.get("doc_ids")
        if doc_ids:
            if isinstance(doc_ids, str):
                doc_ids_filter = [doc_ids]
            else:
                doc_ids_filter = list(doc_ids)

        try:
            hits = self.milvus_store.search_similar(
                query_vector=query_vector,
                top_k=top_k,
                doc_ids_filter=doc_ids_filter,
                timeout_seconds=self.backend_timeout_seconds,
            )
        except Exception as e:
            self.logger.warning("[VECTOR_SEARCH_FALLBACK] Milvus search failed, falling back to BM25: %s", e)
            return []

        rows = []
        for hit in hits:
            entity = hit.entity
            row = {
                "doc_id": entity.get("doc_id"),
                "chunk_index": entity.get("chunk_index"),
                "chunk_text": entity.get("chunk_text") or entity.get("text") or "",
                "score": hit.distance,
                "vector_score": hit.distance,
                "bm25_score": 0.0,
            }
            if not _matches_filters(row, filters):
                continue
            rows.append(row)

        scores = _normalize_scores([row["vector_score"] for row in rows])
        for row, score in zip(rows, scores):
            row["score"] = score
            row["vector_score"] = score

        return rows

    def _bm25_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        try:
            hits = self.bm25_index.search(query, top_k=top_k)
        except Exception as e:
            raise RetrievalError(f"bm25_search_failed: {e}") from e

        rows = []
        for hit in hits:
            doc_id = hit.get("doc_id")
            chunk_index = hit.get("chunk_index")
            row = {
                "doc_id": doc_id,
                "chunk_index": chunk_index,
                "chunk_text": hit.get("chunk_text", hit.get("text")),
                "score": hit.get("score", 0.0),
                "vector_score": 0.0,
                "bm25_score": hit.get("score", 0.0),
            }

            doc_meta = self._load_document_meta(str(doc_id))
            if not _matches_filters(row, filters, doc_meta):
                continue
            rows.append(row)

        bm25_scores = _normalize_scores([row["bm25_score"] for row in rows])
        for row, score in zip(rows, bm25_scores):
            row["score"] = score
            row["bm25_score"] = score

        return rows

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

        if not isinstance(self.rerank_top_n, int) or not 1 <= self.rerank_top_n <= 100:
            raise RetrievalParameterError(
                "invalid_rerank_top_n: rerank_top_n must be an integer from 1 to 100"
            )

        invalid_rerank_modes = self.rerank_modes - self.VALID_MODES
        if invalid_rerank_modes:
            allowed = ", ".join(sorted(self.VALID_MODES))
            raise RetrievalParameterError(
                f"invalid_rerank_modes: rerank modes must be selected from {allowed}"
            )

        if self.backend_timeout_seconds <= 0:
            raise RetrievalParameterError(
                "invalid_backend_timeout: backend timeout must be positive"
            )

        if filters is not None and not isinstance(filters, dict):
            raise RetrievalParameterError("invalid_filters: filters must be a dict or None")

        try:
            float(min_score)
        except (TypeError, ValueError) as exc:
            raise RetrievalParameterError("invalid_min_score: min_score must be numeric") from exc

    def _normalize_results(
        self,
        raw_results: List[Dict],
        filters: Dict,
        min_score: float,
    ) -> List[Dict]:
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

            doc_meta = self._load_document_meta(doc_id)
            if not _matches_filters(item, filters, doc_meta):
                continue

            if float(score) < min_score:
                continue

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

    def _log(
        self,
        trace_id: str,
        mode: str,
        top_k: int,
        results: int,
        latency_ms: int,
        top_scores: List[float],
        observation: Optional[Dict] = None,
        query: str = "",
    ) -> None:
        observation = observation or default_observation(mode)
        score_text = ",".join(f"{score:.4f}" for score in top_scores)
        self.logger.info(
            "[RETRIEVAL] trace_id=%s mode=%s top_k=%s results=%s latency=%sms "
            "top_scores=%s query_hash=%s rewrite_status=%s rewrite_latency_ms=%s "
            "query_count=%s selected_route=%s retriever_paths=%s "
            "candidate_count_by_path=%s unique_candidate_count=%s "
            "fallback_reason=%s rerank_used=%s protected_original_count=%s "
            "protected_variant_unique_count=%s total_latency_ms=%s",
            trace_id,
            mode,
            top_k,
            results,
            latency_ms,
            score_text,
            hashlib.sha256(query.encode("utf-8")).hexdigest()[:12] if query else "-",
            observation["rewrite_status"],
            observation["rewrite_latency_ms"],
            observation["query_count"],
            observation["selected_route"],
            observation["retriever_paths"],
            observation["candidate_count_by_path"],
            observation["unique_candidate_count"],
            observation["fallback_reason"],
            observation["rerank_used"],
            observation["protected_original_count"],
            observation["protected_variant_unique_count"],
            latency_ms,
        )
