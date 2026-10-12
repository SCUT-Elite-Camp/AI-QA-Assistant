import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from data_persistence.vector import matches_filters, normalize_filters
from tool_layer.base_tool import BaseTool
from tool_layer.evidence_metadata import chunk_metadata, source_metadata


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
        navigation_mode = kwargs.get("navigation_mode", "direct")

        results = self.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            min_score=self.min_score,
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
        navigation_mode: str = "direct",
    ) -> List[Dict]:
        self._validate_params(query, top_k, mode, filters, min_score)
        if type(navigation_mode) is not str or navigation_mode not in {
            "direct", "hierarchical", "hybrid",
        }:
            raise RetrievalParameterError(
                "invalid_navigation_mode: expected direct, hierarchical, or hybrid"
            )
        if os.getenv("HIERARCHICAL_NAVIGATION_ENABLED", "false").lower() not in {
            "1", "true", "yes",
        }:
            navigation_mode = "direct"
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
            raw_results = self._search_internal(query.strip(), top_k, mode, filters)
            if focused_doc_id:
                raw_results = self._focus_scoped_section(query, focused_doc_id, raw_results, top_k)
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
        top_scores = [row["score"] for row in results[:5]]
        self._log(trace, mode, top_k, len(results), latency_ms, top_scores)
        return results

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
        normalized_query = " ".join(re.findall(r"[a-z0-9]+", query.casefold()))
        matching = []
        for doc_id in allowed:
            title = str(self._load_document_meta(doc_id).get("title") or "")
            title_words = re.findall(r"[a-z0-9]+", title.casefold())
            if len(title_words) >= 3 and " ".join(title_words) in normalized_query:
                matching.append(doc_id)
        return {**filters, "doc_ids": matching} if len(matching) == 1 else filters

    def _search_sections(self, query: str, filters: Dict, *, top_k: int) -> List[Dict]:
        """Rank version-local Section metadata after document authorization."""
        tokens = [token.casefold() for token in query.split() if token][:20]
        hits: List[Dict] = []
        if not self.documents_dir.exists():
            return hits
        for path in self.documents_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as source:
                    document = json.load(source)
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(document, dict) or document.get("active_version", True) is not True:
                continue
            if not _matches_filters(document, filters, document):
                continue
            document_id = str(document.get("doc_id") or path.stem)
            for section in document.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                text = " ".join([
                    str(section.get("title") or ""),
                    " / ".join(str(value) for value in section.get("section_path") or []),
                    str(section.get("extractive_summary") or section.get("summary") or ""),
                ]).casefold()
                score = sum(text.count(token) for token in tokens)
                if score:
                    item = dict(section)
                    item["doc_id"] = document_id
                    item["score"] = float(score)
                    hits.append(item)
        hits.sort(key=lambda item: (-float(item["score"]), str(item.get("id") or "")))
        return hits[:top_k]

    def _authorized_sections(self, filters: Dict) -> Dict[str, Dict]:
        sections: Dict[str, Dict] = {}
        if not self.documents_dir.exists():
            return sections
        for path in self.documents_dir.glob("*.json"):
            document = self._load_document_meta(path.stem)
            if not document or document.get("active_version", True) is not True:
                continue
            if not _matches_filters(document, filters, document):
                continue
            doc_id = str(document.get("doc_id") or path.stem)
            for section in document.get("sections") or []:
                if not isinstance(section, dict) or not section.get("id"):
                    continue
                row = dict(section)
                row["doc_id"] = doc_id
                sections[str(row["id"])] = row
        return sections

    def browse_document_outline(
        self,
        query: str,
        *,
        doc_ids: Optional[List[str]] = None,
        top_k: int = 8,
    ) -> List[Dict]:
        """Return Section navigation metadata, never citation Evidence."""
        if os.getenv("HIERARCHICAL_NAVIGATION_ENABLED", "false").lower() not in {
            "1", "true", "yes",
        }:
            return []
        if doc_ids is not None and (
            not isinstance(doc_ids, list)
            or len(doc_ids) > 100
            or any(not isinstance(value, str) for value in doc_ids)
        ):
            raise RetrievalParameterError("doc_ids must contain at most 100 strings")
        self._validate_params(query, top_k, "bm25", None, 0.0)
        filters = _normalize_public_filters({"doc_ids": doc_ids} if doc_ids else None)
        matched = self._search_sections(query.strip(), filters, top_k=max(1, top_k // 2))
        from shared_runtime.document_sections import select_outline_candidates

        return select_outline_candidates(
            self._authorized_sections(filters).values(), matched, limit=top_k
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
        """Retrieve authoritative chunks constrained by selected Section IDs."""
        if os.getenv("HIERARCHICAL_NAVIGATION_ENABLED", "false").lower() not in {
            "1", "true", "yes",
        }:
            return []
        if (
            not isinstance(section_ids, list)
            or not 1 <= len(section_ids) <= 20
            or any(not isinstance(value, str) for value in section_ids)
        ):
            raise RetrievalParameterError("section_ids must contain 1 to 20 strings")
        if doc_ids is not None and (
            not isinstance(doc_ids, list)
            or len(doc_ids) > 100
            or any(not isinstance(value, str) for value in doc_ids)
        ):
            raise RetrievalParameterError("doc_ids must contain at most 100 strings")
        self._validate_params(query, top_k, mode, None, 0.0)
        requested = list(dict.fromkeys(value for value in section_ids if value))
        if not requested:
            raise RetrievalParameterError(
                "section_ids must contain at least one Section ID"
            )
        filters = _normalize_public_filters({"doc_ids": doc_ids} if doc_ids else None)
        sections = self._authorized_sections(filters)
        selected = [sections[value] for value in requested if value in sections]
        chunk_ids = sorted({
            str(chunk_id)
            for section in selected
            for chunk_id in section.get("evidence_ids") or []
            if str(chunk_id)
        })
        if not chunk_ids:
            return []
        matched_by_chunk: Dict[str, List[str]] = {}
        for section in selected:
            section_id = str(section["id"])
            for chunk_id in section.get("evidence_ids") or []:
                matched_by_chunk.setdefault(str(chunk_id), []).append(section_id)
        scoped_filters = dict(filters)
        scoped_filters["chunk_ids"] = chunk_ids
        raw = self._search_internal(query.strip(), max(top_k * 3, 20), mode, scoped_filters)
        rows = self._normalize_results(raw, scoped_filters, 0.0)[:top_k]
        for row in rows:
            row["matched_section_ids"] = matched_by_chunk.get(
                str(row.get("chunk_id") or ""), []
            )
        return rows

    def _load_section_evidence(
        self,
        section_hits: List[Dict],
        filters: Dict,
        min_score: float,
        limit: int,
    ) -> List[Dict]:
        selected: Dict[str, set[str]] = {}
        for section in section_hits:
            if section.get("quality") == "low" or int(section.get("level") or 0) <= 0:
                continue
            doc_id = str(section.get("doc_id") or "")
            if doc_id:
                selected.setdefault(doc_id, set()).update(
                    str(value) for value in section.get("evidence_ids") or []
                )
        raw: List[Dict] = []
        for doc_id, chunk_ids in selected.items():
            document = self._load_document_meta(doc_id)
            if not document or document.get("active_version", True) is not True:
                continue
            if not _matches_filters(document, filters, document):
                continue
            for chunk in document.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                chunk_id = str(chunk.get("chunk_id") or "")
                if chunk_id not in chunk_ids:
                    continue
                raw.append({
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk.get("index", 0),
                    "text": chunk.get("text", ""),
                    "score": 1.0,
                    "title": document.get("title", ""),
                    "source_url": document.get("source_url", ""),
                })
                if len(raw) >= limit:
                    break
            if len(raw) >= limit:
                break
        return self._normalize_results(raw, filters, min_score)

    @staticmethod
    def _fuse_navigation(
        direct: List[Dict],
        scoped: List[Dict],
        *,
        direct_weight: float,
        scoped_weight: float,
        rrf_k: int = 60,
    ) -> List[Dict]:
        by_id: Dict[str, Dict] = {}
        scores: Dict[str, float] = {}
        for weight, rows in ((direct_weight, direct), (scoped_weight, scoped)):
            for rank, item in enumerate(rows, 1):
                key = str(item.get("chunk_id") or "")
                if not key:
                    continue
                by_id.setdefault(key, dict(item))
                scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank)
        maximum = max(scores.values(), default=1.0)
        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        output: List[Dict] = []
        for key in ordered:
            item = dict(by_id[key])
            item["score"] = min(1.0, scores[key] / maximum) if maximum else 0.0
            output.append(item)
        return output

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

        candidate_limit = max(top_k * 5, 20)
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
        return _hybrid_search(vector_rows, bm25_rows, top_k, self.rrf_k)

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
        from pipeline.embedder import embed_texts

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
