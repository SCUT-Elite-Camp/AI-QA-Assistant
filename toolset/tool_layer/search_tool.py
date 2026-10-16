import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from data_persistence.vector import matches_filters, normalize_filters
from .base_tool import BaseTool
from .evidence_metadata import chunk_metadata, source_metadata
from retrieval.reranker import candidate_count, enabled as rerank_enabled, rerank


logging.getLogger(__name__).addHandler(logging.NullHandler())

_PUBLIC_FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})
_PROVENANCE_RESULT_FIELDS = (
    "chunk_type", "block_id", "table_id", "page_number", "bbox_json", "metadata_json",
    "page_regions",
)


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


def _bbox_list(value) -> list[float] | None:
    if isinstance(value, dict):
        value = [value.get(key) for key in ("x0", "y0", "x1", "y1")]
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) and result[2] >= result[0] and result[3] >= result[1] else None


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if item not in (None, "")))


def _page_regions_from_provenance(page_number, bbox_json, metadata_json) -> list[dict]:
    """Normalize structured regions, falling back to legacy scalar provenance."""
    metadata: dict = {}
    if isinstance(metadata_json, str) and metadata_json:
        try:
            parsed = json.loads(metadata_json)
            metadata = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    normalized: list[dict] = []
    raw_regions = metadata.get("page_regions", [])
    if isinstance(raw_regions, list):
        for item in raw_regions:
            if not isinstance(item, dict):
                continue
            bbox = _bbox_list(item.get("bbox"))
            try:
                region_page = int(item.get("page_number", 0))
                confidence = float(item.get("confidence", 1.0))
            except (TypeError, ValueError):
                continue
            if region_page < 1 or bbox is None or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                continue
            normalized.append({
                "page_number": region_page,
                "bbox": bbox,
                "block_ids": _string_list(item.get("block_ids", [])),
                "table_ids": _string_list(item.get("table_ids", [])),
                "sources": _string_list(item.get("sources", [])),
                "confidence": confidence,
            })
    if normalized:
        return sorted(normalized, key=lambda item: item["page_number"])

    try:
        scalar_page = int(page_number or 0)
        scalar_bbox = _bbox_list(json.loads(bbox_json)) if bbox_json else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if scalar_page < 1 or scalar_bbox is None:
        return []
    source = metadata.get("source")
    return [{
        "page_number": scalar_page,
        "bbox": scalar_bbox,
        "block_ids": [],
        "table_ids": [],
        "sources": [source] if isinstance(source, str) and source else [],
        "confidence": 1.0,
    }]


def _chunk_key(row: Dict) -> tuple:
    return (str(row.get("doc_id")), int(row.get("chunk_index", 0)))


def _matches_filters(item: Dict, filters: Dict, doc_meta: Optional[Dict] = None) -> bool:
    combined = dict(doc_meta or {})
    combined.update(
        {key: value for key, value in item.items() if value not in (None, "")}
    )
    return matches_filters(combined, filters)


def _normalize_public_filters(filters: Optional[Dict]) -> Dict:
    if isinstance(filters, dict):
        unknown = set(filters) - _PUBLIC_FILTER_KEYS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise RetrievalParameterError(
                f"invalid_filters: unsupported filter keys: {names}"
            )
        if "doc_id" in filters and not isinstance(filters["doc_id"], str):
            raise RetrievalParameterError("invalid_filters: doc_id must be a string")
        if "doc_ids" in filters and not isinstance(filters["doc_ids"], list):
            raise RetrievalParameterError("invalid_filters: doc_ids must be an array")
    try:
        return normalize_filters(filters)
    except ValueError as exc:
        raise RetrievalParameterError(f"invalid_filters: {exc}") from exc


def _hybrid_search(vector_rows: list[dict], bm25_rows: list[dict], top_k: int, rrf_k: int = 60, bm25_weight: float = 1.0) -> list[dict]:
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
            rrf_score += bm25_weight / (rrf_k + bm25_rank[key])

        merged[key]["score"] = rrf_score
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
    ):
        from data_persistence.documents import resolve_documents_dir

        default_documents_dir = resolve_documents_dir()
        self.documents_dir = (
            Path(documents_dir) if documents_dir else
            default_documents_dir
        )
        self.bm25_path = Path(os.getenv("BM25_INDEX_PATH", str(default_documents_dir.parent / "bm25_index.pkl")))

        self.backend = backend
        self.logger = logger or logging.getLogger(__name__)
        self.latest_results = []
        self.min_score = min_score
        self.rrf_k = rrf_k

        self._milvus_store = None
        self._bm25_index = None

    @property
    def milvus_store(self):
        if self._milvus_store is None:
            from data_persistence.vector import MilvusStore
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
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "mode": {
                    "type": "string",
                    "description": "Retrieval mode: 'vector', 'bm25', or 'hybrid'.",
                    "default": "hybrid",
                    "enum": ["vector", "bm25", "hybrid"],
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "doc_ids": {"type": "array", "items": {"type": "string"}},
                        "space": {"type": "string"},
                        "doc_type": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> Any:
        query = kwargs.get("query")
        top_k = kwargs.get("top_k", 5)
        mode = kwargs.get("mode", "hybrid")
        filters = kwargs.get("filters")

        results = self.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            min_score=self.min_score,
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
    ) -> List[Dict]:
        self._validate_params(query, top_k, mode, filters, min_score)
        started = time.perf_counter()
        trace = trace_id or "-"
        filters = _normalize_public_filters(filters)
        filters = self._narrow_week_scope(query, filters)
        dated_filters = self._narrow_dated_scope(query, filters)
        focused_doc_id = None
        if len(filters.get("doc_ids") or []) > 1 and len(dated_filters.get("doc_ids") or []) == 1:
            focused_doc_id = dated_filters["doc_ids"][0]
        filters = dated_filters
        if not focused_doc_id:
            named_filters = self._narrow_named_scope(query, filters)
            if len(filters.get("doc_ids") or []) > 1 and len(named_filters.get("doc_ids") or []) == 1:
                focused_doc_id = named_filters["doc_ids"][0]
            filters = named_filters

        try:
            count = candidate_count(top_k) if rerank_enabled() else top_k
            raw_results = self._search_internal(query.strip(), count, mode, filters)
            if focused_doc_id:
                raw_results = self._focus_scoped_section(query, focused_doc_id, raw_results, count)
            results = self._normalize_results(raw_results, filters, float(min_score))
            results = self._rank_results(query, results, top_k)
        except Exception as exc:
            if getattr(exc, "source_access_failure", False):
                raise
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
        results = self._with_context(results, filters)
        top_scores = [row["score"] for row in results[:5]]
        self._log(trace, mode, top_k, len(results), latency_ms, top_scores)
        return results

    def search_direct(self, query: str, top_k: int = 5, mode: str = "hybrid",
                      filters: Optional[Dict] = None, min_score: float = 0.0,
                      trace_id: Optional[str] = None) -> List[Dict]:
        """One original-query search, without title/date routing or section expansion."""
        self._validate_params(query, top_k, mode, filters, min_score)
        filters = _normalize_public_filters(filters)
        started = time.perf_counter()
        try:
            count = candidate_count(top_k) if rerank_enabled() else top_k
            raw = self._search_internal(query, count, mode, filters)
            rows = self._rank_results(query, self._normalize_results(raw, filters, float(min_score)), top_k)
            rows = self._with_context(rows, filters)
        except Exception as exc:
            if getattr(exc, "source_access_failure", False):
                raise
            self._log(trace_id or "-", mode, top_k, 0, int((time.perf_counter() - started) * 1000), [])
            raise RetrievalError("retrieval_error: direct search failed") from exc
        self._log(trace_id or "-", mode, top_k, len(rows), int((time.perf_counter() - started) * 1000),
                  [row["score"] for row in rows[:5]])
        return rows

    def _rank_results(self, query, rows, top_k):
        if rerank_enabled():
            # A stale vector hit must not become an input to a semantic model
            # before it has matched a current authoritative source chunk.
            trusted = [row for row in rows if row.get('read_status') == 'original_excerpt_loaded']
            if len(trusted) != len(rows):
                self.logger.warning('RERANK_UNTRUSTED_HITS_EXCLUDED count=%d', len(rows)-len(trusted))
            rows = trusted
        return rerank(query, rows, top_k)

    def _with_context(self, rows, filters):
        from retrieval.context import attach_context
        documents = {}
        def lookup(parent, neighbor_id):
            doc_id = parent['doc_id']
            if doc_id not in documents:
                documents[doc_id] = self._load_document_meta(doc_id)
            document = documents[doc_id]
            for chunk in document.get('chunks') or []:
                if chunk.get('chunk_id') == neighbor_id:
                    raw = {'doc_id':doc_id, 'chunk_index':chunk['index'],
                           'chunk_text':chunk.get('text') or '', 'score':parent['score']}
                    normalized = self._normalize_results([raw], filters, 0)
                    return normalized[0] if normalized else None
            return None
        return attach_context(rows, lookup)

    def _focus_scoped_section(self, query: str, doc_id: str, raw: List[Dict], top_k: int) -> List[Dict]:
        """Keep the relevant section together after selecting one authorized page."""
        document = self._load_document_meta(doc_id)
        chunks = document.get("chunks") or []
        sections: Dict[str, List[Dict]] = {}
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            path = chunk.get("section_path") or []
            if not isinstance(path, list) or not path:
                continue
            heading = str(path[-1]).strip()
            if not heading or heading == document.get("title"):
                continue
            sections.setdefault(heading, []).append(chunk)
        query_words = set(re.findall(r"[a-z]{3,}", query.casefold()))
        title_text = str(document.get("title") or "").casefold()
        title_words = set(re.findall(r"[a-z]{3,}", title_text))
        stopwords = {
            "how", "does", "the", "current", "what", "which", "from", "this", "that", "meeting",
            "list", "all", "four", "and", "for", "with", "into", "their", "there", "where",
        }
        meaningful_words = query_words - title_words - stopwords
        ordered_words = re.findall(r"[a-z]{3,}", query.casefold())
        query_bigrams = {
            " ".join(pair) for pair in zip(ordered_words, ordered_words[1:])
            if pair[0] not in stopwords and pair[1] not in stopwords
        }
        best: List[Dict] = []
        best_score = 0
        for heading, group in sections.items():
            section_text = " ".join(str(item.get("text") or "") for item in group).casefold()
            heading_text = heading.casefold()
            heading_matches = query_words & set(re.findall(r"[a-z]{3,}", heading_text))
            score = 4 * len(heading_matches - title_words) + len(heading_matches & title_words)
            score += 2 * len(meaningful_words & set(re.findall(r"[a-z]{3,}", section_text)))
            score += sum(
                (4 if phrase in title_text else 20)
                for phrase in query_bigrams
                if phrase in heading_text or phrase in section_text
            )
            if score > best_score:
                best_score, best = score, group
        if best_score < 6:
            return raw
        focused = []
        for position, chunk in enumerate(best[:top_k]):
            focused.append({
                "doc_id": doc_id,
                "chunk_index": chunk.get("index"),
                "chunk_text": chunk.get("text", ""),
                "title": document.get("title", ""),
                "source_url": document.get("source_url", ""),
                "score": 1.0 - position * 0.001,
            })
        selected = {(str(row.get("doc_id")), row.get("chunk_index")) for row in focused}
        return (focused + [row for row in raw if (str(row.get("doc_id")), row.get("chunk_index")) not in selected])[:top_k]

    def _narrow_named_scope(self, query: str, filters: Dict) -> Dict:
        """Match a full document title only within the caller's authorized allowlist."""
        allowed = filters.get("doc_ids") or []
        if len(allowed) < 2:
            return filters
        from tool_layer.document_matching import named_document_ids
        matching = named_document_ids(query, [{"doc_id": i, "title": self._load_document_meta(i).get("title", "")} for i in allowed])
        return {**filters, "doc_ids": matching} if matching else filters

    def _narrow_week_scope(self, query: str, filters: Dict) -> Dict:
        """Resolve a single named sprint inside an explicit document allowlist."""
        weeks = set(re.findall(r"(?<!\w)W\d{2}(?!\w)", query, re.IGNORECASE))
        allowed = filters.get("doc_ids") or []
        if len(weeks) != 1 or len(allowed) < 2:
            return filters
        week = next(iter(weeks)).casefold()
        matching = [doc_id for doc_id in allowed if week in str(self._load_document_meta(doc_id).get("title", "")).casefold()]
        return {**filters, "doc_ids": matching} if matching else filters

    def _narrow_dated_scope(self, query: str, filters: Dict) -> Dict:
        """Resolve a dated comparison target within its authorized documents."""
        dates = {(int(y), int(m), int(d)) for y, m, d in re.findall(
            r"(?<!\d)(\d{4})[-_/ +](\d{1,2})[-_/ +](\d{1,2})(?!\d)", query
        )}
        months = {name: i for i, name in enumerate(
            ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1
        )}
        for name, day, year in re.findall(
            r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", query, re.IGNORECASE
        ):
            dates.add((int(year or 0), months[name.casefold()], int(day)))
        allowed = filters.get("doc_ids") or []
        if len(dates) != 1 or len(allowed) < 2:
            return filters
        year, month, day = next(iter(dates))
        matching = []
        for doc_id in allowed:
            title = str(self._load_document_meta(doc_id).get("title", ""))
            title_dates = re.findall(r"(?<!\d)(\d{4})[-_/ +](\d{1,2})[-_/ +](\d{1,2})(?!\d)", title)
            if any(int(m) == month and int(d) == day and (not year or int(y) == year) for y, m, d in title_dates):
                matching.append(doc_id)
        return {**filters, "doc_ids": matching} if matching else filters

    def _search_internal(self, query: str, top_k: int, mode: str, filters: Dict) -> List[Dict]:
        # 空白名单短路：doc_ids 显式为空列表表示用户无可访问文件，直接返回空结果。
        if self._has_empty_doc_id_allowlist(filters):
            return []

        if self.backend is not None:
            return self.backend.search(query, top_k=top_k, mode=mode, filters=filters)

        candidate_limit = candidate_count(top_k) if rerank_enabled() else max(top_k * 5, 20)
        if mode == "vector":
            return self._vector_search(query, candidate_limit, filters)[:top_k]
        if mode == "bm25":
            return self._bm25_search(query, candidate_limit, filters)[:top_k]

        vector_rows = []
        try:
            vector_rows = self._vector_search(query, candidate_limit, filters)
        except Exception as e:
            self.logger.warning(f"Vector search failed, falling back to BM25: {e}")

        bm25_rows = self._bm25_search(query, candidate_limit, filters)
        if not vector_rows:
            return bm25_rows[:top_k]
        if not bm25_rows:
            return vector_rows[:top_k]
        # The active English embedding is weak on CJK queries. Preserve both
        # channels while giving explicit lexical matches more rank weight.
        lexical_weight = 2.0 if re.search(r"[\u3400-\u9fff]", query) else 1.0
        return _hybrid_search(vector_rows, bm25_rows, top_k, self.rrf_k, lexical_weight)

    @staticmethod
    def _has_empty_doc_id_allowlist(filters: Dict) -> bool:
        """判断 filters 是否携带显式空白名单（doc_ids 为空列表）。"""
        if not filters:
            return False
        for key in ("doc_ids", "doc_id"):
            if key in filters:
                value = filters[key]
                return isinstance(value, (list, tuple, set)) and len(value) == 0
        return False

    def _vector_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        from pipeline.indexing.embedder import embed_texts

        query_vector = embed_texts([query])[0]

        try:
            hits = self.milvus_store.search_similar(
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
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
                "title": entity.get("title") or "",
                "space": entity.get("space") or "",
                "doc_type": entity.get("doc_type") or "",
                "source_url": entity.get("source_url") or "",
                **{field: entity.get(field) for field in _PROVENANCE_RESULT_FIELDS},
            }
            row["page_regions"] = _page_regions_from_provenance(
                row.get("page_number"),
                row.get("bbox_json"),
                row.get("metadata_json"),
            )
            if not _matches_filters(row, filters):
                continue
            if re.fullmatch(r"(?:表格|Table)[:：]\s*[^\n]+", str(row['chunk_text']).strip(), re.I):
                continue
            rows.append(row)

        scores = _normalize_scores([row["vector_score"] for row in rows])
        for row, score in zip(rows, scores):
            row["score"] = score
            row["vector_score"] = score

        return rows

    def _bm25_search(self, query: str, top_k: int, filters: Dict) -> List[Dict]:
        try:
            hits = self.bm25_index.search(query, top_k=top_k, filters=filters)
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
            if re.fullmatch(r"(?:表格|Table)[:：]\s*[^\n]+", str(row['chunk_text']).strip(), re.I):
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
        if type(query) is not str or not query.strip():
            raise RetrievalParameterError(
                "invalid_query: query must be a non-empty string"
            )

        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise RetrievalParameterError("invalid_top_k: top_k must be an integer from 1 to 20")

        if type(mode) is not str or mode not in self.VALID_MODES:
            allowed = ", ".join(sorted(self.VALID_MODES))
            raise RetrievalParameterError(f"invalid_mode: mode must be one of {allowed}")

        _normalize_public_filters(filters)

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
            if doc_meta.get("active_version", True) is not True:
                continue
            if not _matches_filters(item, filters, doc_meta):
                continue

            if float(score) < min_score:
                continue

            title = item.get("title") or doc_meta.get("title") or doc_id
            source_url = item.get("source_url") or doc_meta.get("source_url") or ""
            provenance = self._read_provenance(doc_meta, chunk_index, str(chunk_text))

            normalized.append(
                {
                    **source_metadata(doc_meta),
                    **provenance,
                    "doc_id": doc_id,
                    "chunk_id": provenance.get("locator", {}).get("chunk_id") if provenance.get("locator") else item.get("chunk_id") or f"{doc_id}::chunk_{chunk_index}",
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

    @staticmethod
    def _read_provenance(document: Dict, chunk_index: int, text: str) -> Dict:
        for chunk in document.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            try:
                matches_index = int(chunk.get("index", -1)) == chunk_index
            except (TypeError, ValueError):
                continue
            if matches_index and str(chunk.get("text") or chunk.get("chunk_text") or "") == text:
                # Geometry comes from the current authoritative projection,
                # after the hit's exact text has matched, never from stale vectors.
                metadata = chunk.get("metadata")
                metadata = dict(metadata) if isinstance(metadata, dict) else {}
                metadata.update({
                    "source": chunk.get("source"),
                    "source_pages": chunk.get("source_pages", []),
                    "section_path": chunk.get("section_path", []),
                    "index_text": chunk.get("index_text") or text,
                    "page_regions": chunk.get("page_regions", []),
                })
                bbox = _bbox_list(chunk.get("bbox"))
                return {
                    **chunk_metadata(document, chunk),
                    "chunk_type": chunk.get("chunk_type", "text"),
                    "block_id": chunk.get("block_id", ""),
                    "table_id": chunk.get("table_id", ""),
                    "page_number": chunk.get("page_number"),
                    "page_regions": _page_regions_from_provenance(
                        chunk.get("page_number"),
                        json.dumps(bbox) if bbox else "",
                        json.dumps(metadata),
                    ),
                    "source_pages": chunk.get("source_pages", []),
                }
        return {"read_status": "retrieval_hit", "evidence_ref": None, "locator": None}

    def _load_document_meta(self, doc_id: str) -> Dict:
        if not doc_id or doc_id in {".", ".."} or any(char in doc_id for char in ("/", "\\", ":")):
            return {}
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
