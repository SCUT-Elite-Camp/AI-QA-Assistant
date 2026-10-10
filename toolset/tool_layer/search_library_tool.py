from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextvars import ContextVar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request
from .http_security import urlopen_no_redirect as urlopen

from .base_tool import BaseTool


class SearchLibraryTool(BaseTool):
    """Search a server-authenticated user's active personal library versions."""

    MAX_DOCUMENT_IDS = 100
    MAX_SECTION_IDS = 20
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
            "navigation_mode": "direct",
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
                from pipeline.embedder import embed_texts
                payload["query_vector"] = embed_texts([query])[0]
            except (ImportError, RuntimeError, OSError, ValueError):
                if mode == "vector":
                    return {"error": "library_vector_unavailable", "items": []}
        return self._post("/v1/library/search", payload)

    def browse_outline(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._navigation_payload(
            kwargs,
            include_sections=False,
            top_k_default=8,
            top_k_maximum=12,
        )
        if "error" in payload:
            return payload
        return self._post("/v1/library/outline", payload)

    def search_evidence_in_scope(self, **kwargs: Any) -> dict[str, Any]:
        mode = kwargs.get("mode", "hybrid")
        if type(mode) is not str or mode not in self.VALID_MODES:
            return {"error": "invalid_library_query", "items": []}
        payload = self._navigation_payload(
            kwargs,
            include_sections=True,
            top_k_default=10,
            top_k_maximum=20,
        )
        if "error" in payload:
            return payload
        payload["mode"] = mode
        return self._post("/v1/library/search-scoped", payload)

    def _navigation_payload(
        self,
        kwargs: dict[str, Any],
        *,
        include_sections: bool,
        top_k_default: int,
        top_k_maximum: int,
    ) -> dict[str, Any]:
        context = self._request_context.get()
        if not os.getenv("ATTACHMENT_INTERNAL_SECRET", "") or context is None:
            return {"error": "library_context_unavailable", "items": [], "sections": []}
        owner_id, knowledge_base_id = context
        query_value = kwargs.get("query")
        if type(query_value) is not str:
            return {"error": "invalid_library_query", "items": [], "sections": []}
        query = query_value.strip()
        if not query or len(query) > self.MAX_QUERY_LENGTH:
            return {"error": "invalid_library_query", "items": [], "sections": []}
        top_k = self._validated_top_k(
            kwargs.get("top_k", top_k_default),
            maximum=top_k_maximum,
        )
        if top_k is None:
            return {"error": "invalid_library_query", "items": [], "sections": []}
        payload: dict[str, Any] = {
            "owner_id": owner_id,
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "top_k": top_k,
        }
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None:
            normalized_doc_ids = self._normalize_identifier_list(
                doc_ids,
                minimum_items=0,
                maximum_items=self.MAX_DOCUMENT_IDS,
            )
            if normalized_doc_ids is None:
                return {"error": "invalid_library_query", "items": [], "sections": []}
            payload["doc_ids"] = normalized_doc_ids
        if include_sections:
            section_ids = self._normalize_identifier_list(
                kwargs.get("section_ids"),
                minimum_items=1,
                maximum_items=self.MAX_SECTION_IDS,
            )
            if section_ids is None:
                return {"error": "invalid_library_query", "items": []}
            payload["section_ids"] = section_ids
        return payload

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
