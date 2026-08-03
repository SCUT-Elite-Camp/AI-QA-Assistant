import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
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


def _hybrid_search(vector_rows: list[dict], bm25_rows: list[dict], top_k: int, rrf_k: int = 60) -> list[dict]:
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
    """Agent-facing retrieval tool.

    Supports three retrieval modes:
    - vector: Dense Milvus search only
    - bm25: Sparse BM25 keyword search only
    - hybrid: RRF fusion of vector + BM25 (default)

    Extended with A-MEM agentic search:
    - search_agentic(): Dual-path retrieval (cards + segments)
      with 2-hop BFS graph expansion on knowledge cards.
    """

    VALID_MODES = {"vector", "bm25", "hybrid", "agentic"}

    def __init__(
        self,
        backend=None,
        documents_dir: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        min_score: float = 0.0,
        rrf_k: int = 60,
        rerank_enabled: Optional[bool] = None,
        rerank_pool_size: int = 20,
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

        # Reranker 配置
        self._rerank_pool_size = rerank_pool_size
        self._reranker = None
        # 允许通过参数覆盖环境变量
        if rerank_enabled is not None and not rerank_enabled:
            import os
            self._rerank_disabled = True
        else:
            self._rerank_disabled = False

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
    def reranker(self):
        if self._reranker is None and not self._rerank_disabled:
            from retrieval.reranker import Reranker
            self._reranker = Reranker(
                candidate_pool_size=self._rerank_pool_size,
            )
        return self._reranker

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
                    "description": "Retrieval mode: 'vector', 'bm25', 'hybrid', or 'agentic'.",
                    "default": "hybrid"
                },
                "backend": {
                    "type": "string",
                    "description": "Retrieval backend: 'standard' (chunk-based) or 'agentic' (A-MEM cards+segments+graph).",
                    "default": "standard"
                }
            },
            "required": ["query"]
        }

    def execute(self, **kwargs: Any) -> Any:
        query = kwargs.get("query")
        top_k = kwargs.get("top_k", 5)
        mode = kwargs.get("mode", "hybrid")
        backend = kwargs.get("backend", "standard")

        results = self.search(query=query, top_k=top_k, mode=mode, min_score=self.min_score, backend=backend)
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
        backend: str = "standard",
    ) -> List[Dict]:
        # A-MEM agentic 路由
        if backend == "agentic" or mode == "agentic":
            agentic_mode = "hybrid" if mode == "agentic" else mode
            return self.search_agentic(
                query=query,
                top_k=top_k,
                mode=agentic_mode,
                filters=filters,
                trace_id=trace_id,
            )

        self._validate_params(query, top_k, mode, filters, min_score)
        started = time.perf_counter()
        trace = trace_id or "-"
        filters = filters or {}

        try:
            raw_results = self._search_internal(query.strip(), top_k, mode, filters)
            results = self._normalize_results(raw_results, filters, float(min_score))
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._log(trace, mode, top_k, 0, latency_ms, [])
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

        # ─── 内容去重 ────────────────────────────────────
        if len(results) > 1:
            results = self._deduplicate(results)

        # ─── Reranker 重排序 ─────────────────────────────
        if self.reranker is not None and self.reranker.enabled and len(results) > 1:
            rerank_started = time.perf_counter()
            try:
                results = self.reranker.rerank(
                    query=query,
                    chunks=results,
                    top_k=top_k,
                )
                rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
                self.logger.info(
                    "[RERANK] trace_id=%s candidates=%s rerank_latency=%sms",
                    trace, min(len(results), self._rerank_pool_size), rerank_ms,
                )
            except Exception as exc:
                self.logger.warning("[RERANK] Failed, using original results: %s", exc)

        top_scores = [row["score"] for row in results[:5]]
        self._log(trace, mode, top_k, len(results), latency_ms, top_scores)
        return results

    def search_agentic(
        self,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
        filters: Optional[Dict] = None,
        expand_graph: bool = True,
        trace_id: Optional[str] = None,
    ) -> List[Dict]:
        """A-MEM 风格 agentic 检索：卡片 + 段落双路 + 图谱扩展

        与 search() 的区别：
        - 同时检索 knowledge_cards 和 semantic_segments 两个 Milvus 集合
        - 可选 2-hop BFS 图谱扩展（跟随卡片链接发现关联知识）
        - 卡片结果优先于段落结果

        当知识卡片集合为空或 CardRetriever 不可用时，
        自动回退到标准 chunk 检索（预期行为，非错误）。

        Args:
            query: 查询文本
            top_k: 最终返回数量
            mode: 检索模式 (vector/bm25/hybrid)
            filters: 文档过滤条件
            expand_graph: 是否启用图谱扩展
            trace_id: 追踪 ID

        Returns:
            检索结果列表（兼容现有 SearchTool 格式）
        """
        trace = trace_id or "-"
        self.logger.info(
            "[AGENTIC_SEARCH] trace_id=%s query=%s top_k=%s expand_graph=%s",
            trace, query[:100], top_k, expand_graph,
        )

        # 尝试使用 CardRetriever
        fallback_reason = None
        try:
            results = self._agentic_search_with_cards(
                query, top_k, mode, filters, expand_graph
            )
            if results:
                self.latest_results = results
                return results
            else:
                fallback_reason = "CardRetriever returned empty results"
        except ImportError as e:
            fallback_reason = f"CardRetriever not available: {e}"
        except Exception as e:
            # 预期内的回退：知识卡片集合不存在或为空
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in (
                "collection", "not found", "empty", "no card",
                "not initialized", "does not exist",
            )):
                fallback_reason = f"Knowledge cards unavailable: {e}"
            else:
                # 非预期错误：记录完整日志但仍回退（生产环境容错）
                self.logger.error(
                    "[AGENTIC_SEARCH] Unexpected error in CardRetriever, "
                    "falling back to standard search. "
                    "trace_id=%s error=%s",
                    trace, e,
                    exc_info=True,
                )
                fallback_reason = f"CardRetriever error (fallback): {e}"

        if fallback_reason:
            self.logger.info(
                "[AGENTIC_SEARCH] Falling back: %s", fallback_reason
            )

        # Fallback: 使用标准检索（段落级）
        return self.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            trace_id=trace_id,
        )

    def _agentic_search_with_cards(
        self,
        query: str,
        top_k: int,
        mode: str,
        filters: Optional[Dict],
        expand_graph: bool,
    ) -> List[Dict]:
        """使用 CardRetriever 做双路检索"""
        from knowledge_cards.card_retriever import CardRetriever
        from knowledge_cards.card_store import CardStore
        from pipeline.embedder import embed_texts

        # 创建 CardRetriever
        card_store = CardStore(
            milvus_host="localhost",
            milvus_port="19530",
        )

        retriever = CardRetriever(
            card_store=card_store,
            embedding_fn=embed_texts,
            bm25_card_index=None,      # 后续集成 BM25
            bm25_segment_index=self.bm25_index,
        )

        # 运行异步检索 — 使用 asyncio.run() 统一处理
        import asyncio
        try:
            retriever_results = asyncio.run(
                retriever.search(
                    query=query,
                    top_k=top_k,
                    search_cards=True,
                    search_segments=True,
                    expand_graph=expand_graph,
                )
            )
        except RuntimeError:
            # 可能在已有事件循环的环境中运行（如 FastAPI async handler）
            # 在新线程中执行以避免冲突
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    retriever.search(
                        query=query,
                        top_k=top_k,
                        search_cards=True,
                        search_segments=True,
                        expand_graph=expand_graph,
                    ),
                )
                retriever_results = future.result(timeout=30)

        # 转换为兼容格式
        results = []
        for r in retriever_results:
            results.append({
                "doc_id": r.doc_id,
                "chunk_id": r.card_id or r.segment_id or r.id,
                "chunk_index": 0,
                "chunk_text": r.content,
                "title": r.doc_id,
                "score": r.score,
                "vector_score": r.score,
                "bm25_score": 0.0,
                "source_url": "",
                "source_type": r.source_type,
                "keywords": r.keywords,
                "tags": r.tags,
            })

        # 分数归一化
        scores = _normalize_scores([r["score"] for r in results])
        for r, s in zip(results, scores):
            r["score"] = s

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

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
            )
        except Exception as e:
            raise RetrievalError(f"milvus_search_failed: {e}") from e

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
                "space": entity.get("space", ""),
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

    def _deduplicate(
        self,
        results: List[Dict],
        sim_threshold: float = 0.75,
    ) -> List[Dict]:
        """基于字符 n-gram Jaccard 相似度的近重复内容去重。

        对于相似度超过阈值的 chunk 对，只保留 score 更高的那个。
        这避免了同一文档中相邻/高度重叠的 chunk 同时出现在 top-K 中。

        Args:
            results: 检索结果列表
            sim_threshold: Jaccard 相似度阈值（超过此值视为重复）

        Returns:
            去重后的结果列表（保持原始顺序）
        """
        if len(results) <= 1:
            return results

        def _ngrams(text: str, n: int = 3) -> Set[str]:
            """提取字符级 n-gram 集合"""
            text = re.sub(r"\s+", "", text)
            if len(text) < n:
                return {text}
            return {text[i:i + n] for i in range(len(text) - n + 1)}

        def _jaccard(a: Set[str], b: Set[str]) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)

        kept: List[Dict] = []
        # 按 score 降序排列，确保高分的优先保留
        sorted_results = sorted(
            results,
            key=lambda x: x.get("score", 0.0),
            reverse=True,
        )

        for candidate in sorted_results:
            text = candidate.get("chunk_text", "")
            cand_ngrams = _ngrams(text)
            is_dup = False

            for existing in kept:
                exist_text = existing.get("chunk_text", "")
                # 同文档且相邻 chunk_index 不做去重（它们内容不同但可能相似）
                if (candidate.get("doc_id") == existing.get("doc_id") and
                        abs(candidate.get("chunk_index", 0) -
                            existing.get("chunk_index", 0)) <= 1):
                    continue

                sim = _jaccard(cand_ngrams, _ngrams(exist_text))
                if sim >= sim_threshold:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(candidate)

        return kept

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
    ) -> None:
        score_text = ",".join(f"{score:.4f}" for score in top_scores)
        self.logger.info(
            "[RETRIEVAL] trace_id=%s mode=%s top_k=%s results=%s latency=%sms top_scores=%s",
            trace_id,
            mode,
            top_k,
            results,
            latency_ms,
            score_text,
        )
