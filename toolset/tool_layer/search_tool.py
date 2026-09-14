import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from retrieval.orchestrator import default_observation
from tool_layer.base_tool import BaseTool


logging.getLogger(__name__).addHandler(logging.NullHandler())
_DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
    chunk_ids = filters.get("chunk_ids")
    if chunk_ids is not None:
        allowed_chunks = {chunk_ids} if isinstance(chunk_ids, str) else set(chunk_ids)
        if str(item.get("chunk_id") or "") not in allowed_chunks:
            return False

    for key in ("space", "doc_type"):
        expected = filters.get(key)
        if expected is None:
            continue
        actual = item.get(key) or (doc_meta.get(key) if doc_meta else None)
        if actual != expected:
            return False

    return True


SUPPORTED_DOC_TYPES = frozenset(
    {
        "csv", "doc", "docx", "epub", "htm", "html", "json", "md",
        "markdown", "odp", "ods", "odt", "pdf", "ppt", "pptx", "rst",
        "rtf", "txt", "xls", "xlsx", "xml",
    }
)


def _normalize_public_filters(filters: Optional[Dict]) -> Dict:
    """Validate the Agent-facing filter contract before backend dispatch."""
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise RetrievalParameterError("invalid_filters: filters must be a dict or None")
    unknown = set(filters) - {"doc_id", "doc_ids", "space", "doc_type"}
    if unknown:
        raise RetrievalParameterError(
            "invalid_filters: unsupported keys " + ", ".join(sorted(unknown))
        )
    normalized: Dict = {}
    raw_ids = filters.get("doc_ids")
    if raw_ids is None and filters.get("doc_id") is not None:
        raw_ids = [filters["doc_id"]]
    if raw_ids is not None:
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, (list, tuple, set)):
            raise RetrievalParameterError(
                "invalid_filters: doc_ids must be a string or list of strings"
            )
        values = []
        for value in raw_ids:
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
                raise RetrievalParameterError(
                    "invalid_filters: every doc_id must be a non-empty string up to 128 characters"
                )
            if value.strip() not in values:
                values.append(value.strip())
        if values:
            normalized["doc_ids"] = values
    for key, maximum in (("space", 256), ("doc_type", 64)):
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise RetrievalParameterError(
                f"invalid_filters: {key} must be a non-empty string up to {maximum} characters"
            )
        candidate = value.strip()
        normalized_value = (
            candidate.lower().rsplit("/", 1)[-1].removeprefix(".")
            if key == "doc_type"
            else candidate
        )
        if key == "doc_type" and normalized_value not in SUPPORTED_DOC_TYPES:
            raise RetrievalParameterError(
                "invalid_filters: doc_type must be a supported file extension"
            )
        normalized[key] = normalized_value
    return normalized


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
        neighbor_expansion_enabled: bool = False,
    ):
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.documents_dir = (
            Path(documents_dir) if documents_dir else
            self.project_root / "data-persistence" / "data" / "documents"
        )
        configured_bm25_path = Path(
            os.getenv(
                "BM25_INDEX_PATH",
                str(self.project_root / "data-persistence" / "data" / "bm25_index.pkl"),
            )
        )
        self.bm25_path = (
            configured_bm25_path
            if configured_bm25_path.is_absolute()
            else self.project_root / configured_bm25_path
        )

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
        self.neighbor_expansion_enabled = bool(neighbor_expansion_enabled)

        self._milvus_store = None
        self._section_milvus_store = None
        self._bm25_index = None
        self._section_bm25_index = None

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
    def section_milvus_store(self):
        if self._section_milvus_store is None:
            from storage.milvus_store import MilvusStore
            self._section_milvus_store = MilvusStore(
                collection_name=os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3")
            )
        return self._section_milvus_store

    @property
    def section_bm25_index(self):
        if self._section_bm25_index is None:
            from retrieval.section_bm25_index import SectionBM25Index

            path = Path(SectionBM25Index.default_index_path())
            self._section_bm25_index = (
                SectionBM25Index.load(str(path)) if path.is_file() else SectionBM25Index()
            )
        return self._section_bm25_index

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
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "doc_ids": {"type": "array", "items": {"type": "string"}},
                        "space": {"type": "string"},
                        "doc_type": {
                            "type": "string",
                            "enum": sorted(SUPPORTED_DOC_TYPES),
                            "description": "File extension only; not a content category.",
                        },
                    },
                    "additionalProperties": False,
                },
                "include_neighbors": {
                    "type": "boolean",
                    "description": "Add the previous and next chunk as context after ranking.",
                    "default": False,
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
        include_neighbors = kwargs.get("include_neighbors", False)
        navigation_mode = kwargs.get("navigation_mode", "direct")

        results = self.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            include_neighbors=include_neighbors,
            min_score=self.min_score,
            topic_doc_ids=getattr(self, "topic_doc_ids", None),
            weight_mode=getattr(self, "weight_mode", "auto"),
            consecutive_no_new_docs_count=getattr(self, "consecutive_no_new_docs_count", 0),
            navigation_mode=navigation_mode,
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
                f"context_before: {item.get('context_before', [])}\n"
                f"context_after: {item.get('context_after', [])}\n"
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
        include_neighbors: bool = False,
        navigation_mode: str = "direct",
    ) -> List[Dict]:
        self._validate_params(query, top_k, mode, filters, min_score)
        if navigation_mode not in {"direct", "hierarchical", "hybrid"}:
            raise RetrievalParameterError(
                "invalid_navigation_mode: expected direct, hierarchical, or hybrid"
            )
        started = time.perf_counter()
        trace = trace_id or "-"
        filters = _normalize_public_filters(filters)
        if not isinstance(include_neighbors, bool):
            raise RetrievalParameterError(
                "invalid_include_neighbors: include_neighbors must be boolean"
            )

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
            observation["navigation_mode"] = "direct"
            observation["section_hits"] = 0
            observation["navigation_fallback_reason"] = (
                "explicit_exploration_only" if navigation_mode != "direct" else "none"
            )
            if use_reranker and results:
                rerank_query = observation.get("preferred_rerank_query") or normalized_query
                results = self._rerank(rerank_query, results, trace)

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
        if include_neighbors and self.neighbor_expansion_enabled:
            results = self._expand_neighbors(results)
        top_scores = [row["score"] for row in results[:5]]
        observation["rerank_used"] = bool(use_reranker and results)
        self._log(
            trace, mode, top_k, len(results), latency_ms, top_scores,
            observation, normalized_query,
        )
        return results

    def _search_sections(
        self,
        query: str,
        filters: Dict,
        *,
        top_k: int,
    ) -> List[Dict]:
        """Search version-aware derived sections stored with enterprise documents."""
        tokens = [token.casefold() for token in query.split() if token][:20]
        sparse_hits: List[Dict] = []
        sections_by_id, authorized_doc_ids = self._load_authorized_sections(filters)
        if not sections_by_id:
            return []
        for item in sections_by_id.values():
            text = str(item.get("navigation_text") or " ".join([
                str(item.get("title") or ""),
                " / ".join(str(value) for value in item.get("section_path") or []),
                str(item.get("extractive_summary") or item.get("summary") or ""),
                str(item.get("llm_summary") or ""),
            ])).casefold()
            score = sum(text.count(token) for token in tokens)
            if score:
                hit = dict(item)
                hit["score"] = float(score)
                sparse_hits.append(hit)
        sparse_hits.sort(key=lambda item: (-float(item["score"]), str(item.get("id") or "")))
        try:
            indexed_sparse = self.section_bm25_index.search(
                query, top_k=max(top_k * 2, 20),
                filters={"doc_ids": authorized_doc_ids},
            )
        except Exception as exc:
            self.logger.warning("[SECTION_BM25_FALLBACK] %s", exc)
            indexed_sparse = []
        if indexed_sparse:
            sparse_hits = [
                {**sections_by_id[str(row["section_id"])], "score": row["score"]}
                for row in indexed_sparse if str(row.get("section_id") or "") in sections_by_id
            ]
        vector_ids: List[str] = []
        if authorized_doc_ids and os.getenv(
            "SECTION_VECTOR_INDEX_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}:
            try:
                from pipeline.embedder import embed_texts

                query_vector = embed_texts([query])[0]
                vector_rows = self.section_milvus_store.search_similar(
                    query_vector=query_vector,
                    top_k=max(top_k * 2, 20),
                    doc_ids_filter=authorized_doc_ids,
                    timeout_seconds=self.backend_timeout_seconds,
                )
                vector_ids = [
                    str(hit.entity.get("chunk_id") or "") for hit in vector_rows
                    if str(hit.entity.get("chunk_id") or "") in sections_by_id
                ]
            except Exception as exc:
                self.logger.warning("[SECTION_VECTOR_FALLBACK] %s", exc)
        scores: Dict[str, float] = {}
        for rank, item in enumerate(sparse_hits, 1):
            section_id = str(item.get("id") or "")
            scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (60 + rank)
        for rank, section_id in enumerate(vector_ids, 1):
            scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (60 + rank)
        ordered = sorted(scores, key=lambda value: (-scores[value], value))[:top_k]
        maximum = max((scores[value] for value in ordered), default=1.0)
        result: List[Dict] = []
        for section_id in ordered:
            item = dict(sections_by_id[section_id])
            item["score"] = round(scores[section_id] / maximum, 6) if maximum else 0.0
            result.append(item)
        return result

    def _load_authorized_sections(self, filters: Dict) -> tuple[Dict[str, Dict], List[str]]:
        """Resolve active documents and Sections before any navigation search."""
        sections_by_id: Dict[str, Dict] = {}
        authorized_doc_ids: List[str] = []
        if not self.documents_dir.exists():
            return sections_by_id, authorized_doc_ids
        for path in self.documents_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as source:
                    document = json.load(source)
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(document, dict) or document.get("active_version", True) is not True:
                continue
            document_id = str(document.get("doc_id") or path.stem)
            if not _DOC_ID_PATTERN.fullmatch(document_id):
                continue
            if not _matches_filters(document, filters, document):
                continue
            authorized_doc_ids.append(document_id)
            for section in document.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                section_id = str(section.get("id") or "")
                if section_id:
                    item = dict(section)
                    item["doc_id"] = document_id
                    sections_by_id[section_id] = item
        return sections_by_id, authorized_doc_ids

    def browse_document_outline(
        self,
        query: str,
        *,
        doc_ids: Optional[List[str]] = None,
        top_k: int = 8,
    ) -> List[Dict]:
        """Return navigation metadata only; rows are never citation Evidence."""
        if os.getenv("HIERARCHICAL_NAVIGATION_ENABLED", "false").lower() not in {
            "1", "true", "yes",
        }:
            return []
        self._validate_params(query, top_k, "bm25", None, 0.0)
        filters = _normalize_public_filters({"doc_ids": doc_ids} if doc_ids else None)
        matched = self._search_sections(
            query.strip(), filters, top_k=max(1, top_k // 2),
        )
        sections, _ = self._load_authorized_sections(filters)
        from shared_runtime.document_sections import select_outline_candidates

        return select_outline_candidates(
            sections.values(), matched, limit=top_k,
        )

    def search_evidence_in_scope(
        self,
        query: str,
        *,
        section_ids: List[str],
        top_k: int = 10,
        mode: str = "hybrid",
        doc_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Rerun authoritative Evidence retrieval inside explicit Sections."""
        if os.getenv("HIERARCHICAL_NAVIGATION_ENABLED", "false").lower() not in {
            "1", "true", "yes",
        }:
            return []
        self._validate_params(query, top_k, mode, None, 0.0)
        requested = list(dict.fromkeys(str(value) for value in section_ids if str(value)))[:20]
        if not requested:
            raise RetrievalParameterError("section_ids must contain at least one Section ID")
        filters = _normalize_public_filters({"doc_ids": doc_ids} if doc_ids else None)
        sections, _ = self._load_authorized_sections(filters)
        selected = [sections[value] for value in requested if value in sections]
        return self._search_scoped_evidence(
            query.strip(), selected, filters, 0.0, max(top_k * 3, 20), mode,
        )[:top_k]

    def _search_scoped_evidence(
        self,
        query: str,
        section_hits: List[Dict],
        filters: Dict,
        min_score: float,
        limit: int,
        mode: str,
    ) -> List[Dict]:
        """Rerun real Evidence retrieval under the selected Section chunk scope."""
        selected: Dict[str, set[str]] = {}
        context_by_chunk: Dict[str, list[str]] = {}
        sections_by_chunk: Dict[str, list[str]] = {}
        for section in section_hits:
            if section.get("quality") == "low" or int(section.get("level") or 0) <= 0:
                continue
            doc_id = str(section.get("doc_id") or "")
            if doc_id:
                values = {str(value) for value in section.get("evidence_ids") or [] if str(value)}
                selected.setdefault(doc_id, set()).update(values)
                context = "\n".join(filter(None, [
                    " / ".join(str(value) for value in section.get("section_path") or []),
                    str(section.get("extractive_summary") or section.get("summary") or ""),
                    str(section.get("llm_summary") or ""),
                ]))
                for chunk_id in values:
                    sections_by_chunk.setdefault(chunk_id, []).append(str(section.get("id") or ""))
                    if context:
                        context_by_chunk.setdefault(chunk_id, []).append(context)
        chunk_ids = sorted({value for values in selected.values() for value in values})
        if not chunk_ids:
            return []
        authorized_docs = sorted(selected)
        existing_docs = filters.get("doc_ids")
        if existing_docs:
            authorized_docs = [value for value in authorized_docs if value in set(existing_docs)]
        if not authorized_docs:
            return []
        scoped_filters = dict(filters)
        scoped_filters["doc_ids"] = authorized_docs
        scoped_filters["chunk_ids"] = chunk_ids
        try:
            raw = self._search_internal(query, limit, mode, scoped_filters)
        except Exception as exc:
            self.logger.warning("[SECTION_SCOPE_FALLBACK] scoped backend search failed: %s", exc)
            raw = []
        normalized = self._normalize_results(raw, scoped_filters, min_score)
        if not normalized and mode in {"bm25", "hybrid"}:
            normalized = self._fallback_scoped_lexical(
                query, selected, filters, min_score, limit,
            )
        for item in normalized:
            chunk_id = str(item.get("chunk_id") or "")
            contexts = context_by_chunk.get(chunk_id) or []
            item["matched_section_ids"] = list(dict.fromkeys(
                value for value in sections_by_chunk.get(chunk_id, []) if value
            ))
            if contexts:
                item["section_context"] = contexts[:3]
                item["rerank_text"] = "\n".join([*contexts[:3], str(item.get("chunk_text") or "")])
        return normalized

    def _fallback_scoped_lexical(
        self,
        query: str,
        selected: Dict[str, set[str]],
        filters: Dict,
        min_score: float,
        limit: int,
    ) -> List[Dict]:
        """Degraded exact-scope lexical search for rolling backend upgrades."""
        tokens = [value.casefold() for value in re.findall(r"[\w\u3400-\u9fff]+", query) if value]
        raw: List[Dict] = []
        for doc_id, allowed in selected.items():
            document = self._load_document_meta(doc_id)
            if not document or document.get("active_version", True) is not True:
                continue
            if not _matches_filters(document, filters, document):
                continue
            for chunk in document.get("chunks") or []:
                chunk_id = str(chunk.get("chunk_id") or "")
                if chunk_id not in allowed:
                    continue
                text = str(chunk.get("text") or "")
                folded = text.casefold()
                score = sum(folded.count(token) for token in tokens)
                if score:
                    raw.append({
                        "doc_id": doc_id, "chunk_id": chunk_id,
                        "chunk_index": chunk.get("index", 0), "text": text,
                        "score": float(score), "bm25_score": float(score),
                        "title": document.get("title", ""),
                        "source_url": document.get("source_url", ""),
                        "version_id": document.get("version_id", ""),
                        "knowledge_base_id": document.get("knowledge_base_id") or document.get("space", ""),
                    })
        raw.sort(key=lambda item: (-float(item["score"]), str(item["chunk_id"])))
        internal_filters = dict(filters)
        internal_filters["doc_ids"] = sorted(selected)
        internal_filters["chunk_ids"] = sorted({value for values in selected.values() for value in values})
        return self._normalize_results(raw[:limit], internal_filters, min_score)

    def _expand_neighbors(self, results: List[Dict]) -> List[Dict]:
        """Attach adjacent context without changing core ranking or scores."""
        expanded = []
        document_cache: Dict[str, Dict] = {}
        for result in results:
            row = dict(result)
            doc_id = row["doc_id"]
            if doc_id not in document_cache:
                document_cache[doc_id] = self._load_document_meta(doc_id)
            document = document_cache[doc_id]
            chunks_by_index = {}
            for chunk in document.get("chunks", []):
                if not isinstance(chunk, dict):
                    continue
                try:
                    chunks_by_index[int(chunk.get("index", 0))] = chunk
                except (TypeError, ValueError):
                    continue
            current_index = int(row["chunk_index"])
            row["context_before"] = self._context_chunk(
                chunks_by_index.get(current_index - 1),
                doc_id,
            )
            row["context_after"] = self._context_chunk(
                chunks_by_index.get(current_index + 1),
                doc_id,
            )
            expanded.append(row)
        return expanded

    @staticmethod
    def _context_chunk(chunk: Optional[Dict], doc_id: str) -> List[Dict]:
        if not chunk:
            return []
        index = int(chunk.get("index", 0))
        return [{
            "role": "context",
            "doc_id": doc_id,
            "chunk_id": chunk.get("chunk_id") or f"{doc_id}::chunk_{index}",
            "chunk_index": index,
            "chunk_text": str(chunk.get("text", "")),
        }]

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

        try:
            hits = self.milvus_store.search_similar(
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
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
                "chunk_id": entity.get("chunk_id"),
                "chunk_index": entity.get("chunk_index"),
                "chunk_text": entity.get("chunk_text") or entity.get("text") or "",
                "score": hit.distance,
                "vector_score": hit.distance,
                "bm25_score": 0.0,
                "title": entity.get("title") or "",
                "space": entity.get("space") or "",
                "doc_type": entity.get("doc_type") or "",
                "source_url": entity.get("source_url") or "",
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
            hits = self.bm25_index.search(query, top_k=top_k, filters=filters)
        except Exception as e:
            raise RetrievalError(f"bm25_search_failed: {e}") from e

        rows = []
        for hit in hits:
            doc_id = hit.get("doc_id")
            chunk_index = hit.get("chunk_index")
            row = {
                "doc_id": doc_id,
                "chunk_id": hit.get("chunk_id"),
                "chunk_index": chunk_index,
                "chunk_text": hit.get("chunk_text", hit.get("text")),
                "score": hit.get("score", 0.0),
                "vector_score": 0.0,
                "bm25_score": hit.get("score", 0.0),
                "title": hit.get("title", ""),
                "space": hit.get("space", ""),
                "doc_type": hit.get("doc_type", ""),
                "source_url": hit.get("source_url", ""),
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

        _normalize_public_filters(filters)

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
            if doc_meta and doc_meta.get("active_version", True) is not True:
                continue
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
                    "space": str(item.get("space") or doc_meta.get("space") or ""),
                    "doc_type": str(
                        item.get("doc_type")
                        or doc_meta.get("doc_type")
                        or ""
                    ),
                    "document_id": str(item.get("document_id") or doc_id),
                    "version_id": str(
                        item.get("version_id") or doc_meta.get("version_id") or ""
                    ),
                    "knowledge_base_id": str(
                        item.get("knowledge_base_id")
                        or doc_meta.get("knowledge_base_id")
                        or doc_meta.get("space")
                        or ""
                    ),
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
            "protected_variant_unique_count=%s navigation_mode=%s section_hits=%s "
            "navigation_fallback_reason=%s total_latency_ms=%s",
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
            observation.get("navigation_mode", "direct"),
            observation.get("section_hits", 0),
            observation.get("navigation_fallback_reason", "none"),
            latency_ms,
        )
