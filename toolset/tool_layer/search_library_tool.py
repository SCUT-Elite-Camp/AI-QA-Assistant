from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextvars import ContextVar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base_tool import BaseTool


class SearchLibraryTool(BaseTool):
    """Search a server-authenticated user's active personal library versions."""

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
                "query": {"type": "string", "description": "资料库检索问题或关键词"},
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
        query = str(kwargs.get("query") or "").strip()
        mode = str(kwargs.get("mode") or "hybrid")
        if not query or mode not in {"hybrid", "vector", "bm25"}:
            return {"error": "invalid_library_query", "items": []}
        try:
            top_k = min(20, max(1, int(kwargs.get("top_k", 5))))
        except (TypeError, ValueError):
            return {"error": "invalid_library_query", "items": []}
        payload: dict[str, Any] = {
            "owner_id": owner_id,
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "top_k": top_k,
            "mode": mode,
            "navigation_mode": "direct",
        }
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list) or len(doc_ids) > 100:
                return {"error": "invalid_library_query", "items": []}
            normalized_doc_ids = [str(value).strip() for value in doc_ids]
            if any(not value or len(value) > 128 for value in normalized_doc_ids):
                return {"error": "invalid_library_query", "items": []}
            payload["doc_ids"] = normalized_doc_ids
        if query.strip() and mode in {"vector", "hybrid"} and os.getenv(
            "ATTACHMENT_VECTOR_INDEX_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}:
            try:
                from pipeline.embedder import embed_texts
                payload["query_vector"] = embed_texts([query])[0]
            except (ImportError, RuntimeError, OSError, ValueError):
                if mode == "vector":
                    return {"error": "library_vector_unavailable", "items": []}
        return self._post("/v1/library/search", payload)

    def browse_outline(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._navigation_payload(kwargs, include_sections=False)
        if "error" in payload:
            return payload
        return self._post("/v1/library/outline", payload)

    def search_evidence_in_scope(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._navigation_payload(kwargs, include_sections=True)
        if "error" in payload:
            return payload
        mode = str(kwargs.get("mode") or "hybrid")
        if mode not in {"hybrid", "vector", "bm25"}:
            return {"error": "invalid_library_query", "items": []}
        payload["mode"] = mode
        return self._post("/v1/library/search-scoped", payload)

    def _navigation_payload(
        self,
        kwargs: dict[str, Any],
        *,
        include_sections: bool,
    ) -> dict[str, Any]:
        context = self._request_context.get()
        if not os.getenv("ATTACHMENT_INTERNAL_SECRET", "") or context is None:
            return {"error": "library_context_unavailable", "items": [], "sections": []}
        owner_id, knowledge_base_id = context
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return {"error": "invalid_library_query", "items": [], "sections": []}
        try:
            top_k = min(20 if include_sections else 12, max(1, int(kwargs.get("top_k", 8))))
        except (TypeError, ValueError):
            return {"error": "invalid_library_query", "items": [], "sections": []}
        payload: dict[str, Any] = {
            "owner_id": owner_id,
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "top_k": top_k,
        }
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list) or len(doc_ids) > 100:
                return {"error": "invalid_library_query", "items": [], "sections": []}
            payload["doc_ids"] = [str(value) for value in doc_ids]
        if include_sections:
            section_ids = kwargs.get("section_ids") or []
            if not isinstance(section_ids, list) or not 1 <= len(section_ids) <= 20:
                return {"error": "invalid_library_query", "items": []}
            payload["section_ids"] = [str(value) for value in section_ids]
        return payload

    @staticmethod
    def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "")
        request = Request(
            f"{os.getenv('ATTACHMENT_SERVICE_URL', 'http://127.0.0.1:8200').rstrip('/')}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=float(os.getenv("ATTACHMENT_SEARCH_TIMEOUT_SECONDS", "8"))) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError, ValueError, json.JSONDecodeError):
            return {"error": "library_tool_unavailable", "items": []}
