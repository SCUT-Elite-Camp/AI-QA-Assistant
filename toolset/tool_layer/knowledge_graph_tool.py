from __future__ import annotations

import hashlib
import hmac
from typing import Any

from storage.knowledge_graph_store import KnowledgeGraphStore

from .base_tool import BaseTool


class SearchKnowledgeGraphTool(BaseTool):
    """Search navigation priors in one trusted enterprise or personal scope."""

    def __init__(
        self,
        store: KnowledgeGraphStore,
        *,
        enterprise_knowledge_base_id: str = "",
    ) -> None:
        self.store = store
        self.enterprise_knowledge_base_id = enterprise_knowledge_base_id.strip()
        self._personal_owner_id = ""
        self._personal_knowledge_base_id = ""

    @property
    def name(self) -> str:
        return "search_knowledge_graph"

    @property
    def description(self) -> str:
        return (
            "Search the authorized LLM Wiki knowledge graph for related documents, "
            "concepts, entities, and Evidence/Section priors. Results are navigation "
            "metadata and must never be cited directly."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source_scope": {
                    "type": "string", "enum": ["enterprise", "personal"],
                    "default": "enterprise",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 12, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def set_personal_context(
        self,
        owner_id: str,
        knowledge_base_id: str,
        token: str,
        *,
        secret: str,
    ) -> None:
        expected = hmac.new(
            secret.encode(), f"{owner_id}:{knowledge_base_id}".encode(), hashlib.sha256,
        ).hexdigest() if secret else ""
        if not expected or not hmac.compare_digest(token, expected):
            self.clear_request_context()
            return
        self._personal_owner_id = owner_id
        self._personal_knowledge_base_id = knowledge_base_id

    def clear_request_context(self) -> None:
        self._personal_owner_id = ""
        self._personal_knowledge_base_id = ""

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        scope = str(kwargs.get("source_scope") or "enterprise")
        if scope == "personal":
            owner = self._personal_owner_id
            kb = self._personal_knowledge_base_id
        else:
            owner = ""
            kb = self.enterprise_knowledge_base_id
        if not kb or (scope == "personal" and not owner):
            return {"error": "knowledge_graph_context_unavailable", "nodes": []}
        nodes = self.store.search(
            str(kwargs.get("query") or ""),
            source_scope=scope,
            owner_id=owner,
            knowledge_base_id=kb,
            top_k=min(12, max(1, int(kwargs.get("top_k", 8)))),
        )
        return {"nodes": nodes, "citation_authority": False}
