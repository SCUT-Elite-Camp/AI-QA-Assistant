from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base_tool import BaseTool


class SearchLibraryTool(BaseTool):
    """Search a server-authenticated user's active personal library versions."""

    def __init__(self) -> None:
        self._owner_id = ""
        self._knowledge_base_id = ""

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
        self._owner_id = owner_id
        self._knowledge_base_id = knowledge_base_id

    def clear_request_context(self) -> None:
        self._owner_id = ""
        self._knowledge_base_id = ""

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "")
        if not secret or not self._owner_id or not self._knowledge_base_id:
            return {"error": "library_context_unavailable", "items": []}
        query = str(kwargs.get("query") or "")
        mode = str(kwargs.get("mode") or "hybrid")
        payload: dict[str, Any] = {
            "owner_id": self._owner_id,
            "knowledge_base_id": self._knowledge_base_id,
            "query": query,
            "top_k": min(20, max(1, int(kwargs.get("top_k", 5)))),
            "mode": mode,
        }
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None:
            payload["doc_ids"] = [str(value) for value in doc_ids]
        if query.strip() and mode in {"vector", "hybrid"} and os.getenv(
            "ATTACHMENT_VECTOR_INDEX_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}:
            try:
                from pipeline.embedder import embed_texts
                payload["query_vector"] = embed_texts([query])[0]
            except (ImportError, RuntimeError, OSError, ValueError):
                if mode == "vector":
                    return {"error": "library_vector_unavailable", "items": []}
        request = Request(
            f"{os.getenv('ATTACHMENT_SERVICE_URL', 'http://127.0.0.1:8200').rstrip('/')}/v1/library/search",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=float(os.getenv("ATTACHMENT_SEARCH_TIMEOUT_SECONDS", "8"))) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError):
            return {"error": "library_tool_unavailable", "items": []}
