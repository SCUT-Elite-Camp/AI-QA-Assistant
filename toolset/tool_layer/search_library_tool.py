from __future__ import annotations

import hashlib
import hmac
import os
import logging
from contextvars import ContextVar
from typing import Any

from .base_tool import BaseTool


class SearchLibraryTool(BaseTool):
    """Search a server-authenticated user's active personal library versions."""

    MAX_DOCUMENT_IDS = 100
    MAX_IDENTIFIER_LENGTH = 128
    MAX_QUERY_LENGTH = 4000
    VALID_MODES = frozenset({"hybrid", "vector", "bm25"})

    def __init__(self) -> None:
        self._request_context: ContextVar[tuple[str, str] | None] = ContextVar(
            f"search_library_context_{id(self)}", default=None
        )

    @property
    def name(self) -> str:
        return "search_library"

    @property
    def description(self) -> str:
        return "检索当前登录用户长期保存的个人资料库；仅返回该用户当前生效版本的证据。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "资料库检索问题或关键词",
                    "minLength": 1,
                    "maxLength": self.MAX_QUERY_LENGTH,
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "doc_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                "mode": {"type": "string", "enum": ["hybrid", "vector", "bm25"], "default": "hybrid"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def set_request_context(self, owner_id: str, knowledge_base_id: str, token: str) -> None:
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "")
        message = f"{owner_id}:{knowledge_base_id}".encode()
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest() if secret else ""
        if not expected or not hmac.compare_digest(token, expected):
            self.clear_request_context()
            return
        self._request_context.set((owner_id, knowledge_base_id))

    def clear_request_context(self) -> None:
        self._request_context.set(None)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "")
        context = self._request_context.get()
        if not secret or context is None:
            return {"error": "library_context_unavailable", "items": []}
        owner_id, knowledge_base_id = context
        query_value = kwargs.get("query")
        if type(query_value) is not str:
            return {"error": "invalid_library_query", "items": []}
        query = query_value.strip()
        mode = kwargs.get("mode", "hybrid")
        if (
            not query
            or len(query) > self.MAX_QUERY_LENGTH
            or type(mode) is not str
            or mode not in self.VALID_MODES
        ):
            return {"error": "invalid_library_query", "items": []}
        top_k = self._validated_top_k(kwargs.get("top_k", 5), maximum=20)
        if top_k is None:
            return {"error": "invalid_library_query", "items": []}
        payload: dict[str, Any] = {
            "owner_id": owner_id,
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "top_k": top_k,
            "mode": mode,
        }
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None:
            normalized_doc_ids = self._normalize_identifier_list(
                doc_ids,
                minimum_items=0,
                maximum_items=self.MAX_DOCUMENT_IDS,
            )
            if normalized_doc_ids is None:
                return {"error": "invalid_library_query", "items": []}
            payload["doc_ids"] = normalized_doc_ids
        if query.strip() and mode in {"vector", "hybrid"} and os.getenv(
            "ATTACHMENT_VECTOR_INDEX_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}:
            try:
                from pipeline.indexing.embedder import embed_texts
                payload["query_vector"] = embed_texts([query])[0]
            except (ImportError, RuntimeError, OSError, ValueError):
                if mode == "vector":
                    return {"error": "library_vector_unavailable", "items": []}
        return self._post(payload)

    @classmethod
    def _normalize_identifier_list(
        cls,
        values: Any,
        *,
        minimum_items: int,
        maximum_items: int,
    ) -> list[str] | None:
        if not isinstance(values, list) or not minimum_items <= len(values) <= maximum_items:
            return None
        if any(type(value) is not str for value in values):
            return None
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > cls.MAX_IDENTIFIER_LENGTH for value in normalized):
            return None
        return normalized

    @staticmethod
    def _validated_top_k(value: Any, *, maximum: int) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            return None
        return value

    @staticmethod
    def _post(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return search_library_evidence(payload)
        except (RuntimeError, OSError, ValueError) as exc:
            if getattr(exc, "source_access_failure", False):
                raise
            return {"error": "library_tool_unavailable", "items": []}


LOGGER = logging.getLogger(__name__)


def search_library_evidence(body, store=None, vector_store=None):
    from data_persistence.file_contracts import LibrarySearchRequest
    from data_persistence.private_files import get_private_file_store
    from data_persistence.vector import get_file_vector_store

    body = LibrarySearchRequest.model_validate(body)
    if store is None:
        store = get_private_file_store()
    # owner/source/library/active are resolved before either FTS5 or Milvus
    # search. Unauthorized rows never enter a retrieval candidate set.
    versions = store.list_library_versions(
        body.owner_id,
        body.knowledge_base_id,
        document_ids=body.doc_ids,
        active_only=True,
    )
    attachment_ids = [str(item["id"]) for item in versions]
    vector_refs = [str(item.get("vector_ref") or item["id"]) for item in versions]
    vector_to_attachment = {
        str(item.get("vector_ref") or item["id"]): str(item["id"])
        for item in versions
    }
    from retrieval.reranker import candidate_count, enabled, rerank
    candidate_k = candidate_count(body.top_k) if enabled() else max(body.top_k * 4, 20)
    direct_lexical = (
        store.search_evidence(attachment_ids, body.query, candidate_k)
        if body.mode in {"bm25", "hybrid"} else []
    )
    direct_vector: list[dict[str, Any]] = []
    vector_degraded = False
    if body.mode in {"vector", "hybrid"} and body.query_vector is not None:
        try:
            backend = vector_store if vector_store is not None else get_file_vector_store()
            if backend is None:
                raise RuntimeError("attachment_vector_index_disabled")
            hits = backend.search_similar(
                body.query_vector, top_k=candidate_k, doc_ids_filter=vector_refs,
                collection_name=backend.collection_name,
            )
            direct_vector = [{
                "attachment_id": hit.entity.get("doc_id"),
                "evidence_id": hit.entity.get("chunk_id"),
                "content": hit.entity.get("chunk_text"), "score": float(hit.score),
            } for hit in hits]
            for row in direct_vector:
                row["attachment_id"] = vector_to_attachment.get(str(row.get("attachment_id")), str(row.get("attachment_id")))
        except Exception as exc:
            vector_degraded = True
            LOGGER.warning(
                "LIBRARY_SEARCH vector degraded knowledge_base_id=%s error=%s",
                body.knowledge_base_id, exc.__class__.__name__,
            )
    evidence = {item["evidence_id"]: item for item in store.list_evidence(attachment_ids)}
    direct = fuse_library_candidates(
        evidence, direct_lexical, direct_vector, mode=body.mode, top_k=candidate_k,
    )
    metadata = {str(item['id']): item for item in versions}
    for item in direct:
        version = metadata.get(str(item.get('attachment_id')), {})
        item.update({key: version.get(key) for key in ('knowledge_base_id', 'document_id', 'version_id')})
        item['source_scope'] = 'personal'
        item['filename'] = version.get('filename', item.get('filename'))
    result = {
        "items": rerank(body.query, direct, body.top_k, text_key="content"),
    }
    if vector_degraded:
        result["degraded"] = ["vector"]
        if body.mode == "vector":
            result["error"] = "library_vector_unavailable"
    from retrieval.context import attach_context
    def lookup_neighbor(parent, neighbor_id):
        neighbor = evidence.get(neighbor_id)
        if not neighbor or neighbor.get('attachment_id') != parent.get('attachment_id'):
            return None
        return {**neighbor, **{key: parent.get(key) for key in (
            'knowledge_base_id', 'document_id', 'version_id', 'source_scope', 'filename')}}
    result['items'] = attach_context(result['items'], lookup_neighbor)
    LOGGER.info(
        "LIBRARY_SEARCH owner_hash=%s knowledge_base_id=%s mode=%s candidates=%s results=%s",
        hashlib.sha256(body.owner_id.encode()).hexdigest()[:12],
        body.knowledge_base_id,
        body.mode,
        len(set(item.get("evidence_id") for item in (*direct_lexical, *direct_vector))),
        len(result["items"]),
    )
    return result


def fuse_library_candidates(
    evidence: dict[str, dict[str, Any]],
    lexical: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    *,
    mode: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Rank-calibrate lexical/vector candidates to a stable 0..1 score."""
    ranks: dict[str, list[float]] = {}

    def add(rows: list[dict[str, Any]]) -> None:
        for rank, row in enumerate(rows, 1):
            evidence_id = str(row.get("evidence_id") or "")
            if evidence_id in evidence:
                ranks.setdefault(evidence_id, []).append(1.0 / (1.0 + 0.12 * (rank - 1)))

    if mode in {"bm25", "hybrid"}:
        add(lexical)
    if mode in {"vector", "hybrid"}:
        add(vector)
    items: list[dict[str, Any]] = []
    for evidence_id, source_scores in ranks.items():
        score = sum(source_scores) / len(source_scores)
        if len(source_scores) > 1:
            score = min(1.0, score + 0.05)
        item = dict(evidence[evidence_id])
        item["score"] = round(min(1.0, max(0.0, score)), 6)
        items.append(item)
    return sorted(items, key=lambda item: (-float(item["score"]), str(item["evidence_id"])))[:top_k]
