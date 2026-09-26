"""Agent-facing Wiki navigation and source-scoped Evidence retrieval tools."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from storage.wiki_store import WikiStore

from .base_tool import BaseTool
from .search_library_tool import SearchLibraryTool
from .search_tool import SearchTool


class _ScopedWikiTool(BaseTool):
    def __init__(self, store: WikiStore, *, enterprise_knowledge_base_id: str = "") -> None:
        self.store = store
        self.enterprise_knowledge_base_id = enterprise_knowledge_base_id.strip()
        self._personal_owner_id = ""
        self._personal_knowledge_base_id = ""

    def set_personal_context(
        self, owner_id: str, knowledge_base_id: str, token: str, *, secret: str,
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

    def _scope(self, value: Any) -> tuple[str, str, str] | None:
        scope = str(value or "enterprise")
        if scope == "personal":
            if not self._personal_owner_id or not self._personal_knowledge_base_id:
                return None
            return scope, self._personal_owner_id, self._personal_knowledge_base_id
        if scope != "enterprise" or not self.enterprise_knowledge_base_id:
            return None
        return scope, "", self.enterprise_knowledge_base_id


class WikiSearchTool(_ScopedWikiTool):
    def __init__(
        self, store: WikiStore, *, enterprise_knowledge_base_id: str = "",
        search_backend: Any | None = None,
    ) -> None:
        super().__init__(store, enterprise_knowledge_base_id=enterprise_knowledge_base_id)
        self.search_backend = search_backend

    @property
    def name(self) -> str:
        return "wiki_search"

    @property
    def description(self) -> str:
        return (
            "Search authorized Wiki pages for cross-document concepts or entities after Direct Evidence has a "
            "coverage gap. Results are navigation metadata, never final citation Evidence."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source_scope": {"type": "string", "enum": ["enterprise", "personal"], "default": "enterprise"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 12, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        context = self._scope(kwargs.get("source_scope"))
        if context is None:
            return {"error": "wiki_context_unavailable", "pages": [], "citation_authority": False}
        scope, owner, kb = context
        search = self.search_backend.search if self.search_backend is not None else self.store.search_pages
        pages = search(
            str(kwargs.get("query") or ""), source_scope=scope, owner_id=owner,
            knowledge_base_id=kb, top_k=min(12, max(1, int(kwargs.get("top_k", 8)))),
        )
        return {"pages": pages, "citation_authority": False}


class WikiReadPageTool(_ScopedWikiTool):
    @property
    def name(self) -> str:
        return "wiki_read_page"

    @property
    def description(self) -> str:
        return (
            "Read one authorized Wiki page selected by wiki_search to understand its supported claims and links. "
            "The page guides exploration but is not citation authority."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "page_ref": {"type": "string", "description": "Wiki page ID or slug returned by wiki_search."},
                "source_scope": {"type": "string", "enum": ["enterprise", "personal"], "default": "enterprise"},
            },
            "required": ["page_ref"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        context = self._scope(kwargs.get("source_scope"))
        if context is None:
            return {"error": "wiki_context_unavailable", "page": None, "citation_authority": False}
        scope, owner, kb = context
        page = self.store.read_page(
            str(kwargs.get("page_ref") or ""), source_scope=scope, owner_id=owner,
            knowledge_base_id=kb,
        )
        return {"page": page, "citation_authority": False}


class WikiReadSourcesTool(_ScopedWikiTool):
    @property
    def name(self) -> str:
        return "wiki_read_sources"

    @property
    def description(self) -> str:
        return (
            "Resolve a Wiki page or claim to original document-version, Section, and Evidence identifiers. "
            "Use those identifiers to retrieve authoritative Evidence before answering."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "claim_id": {"type": "string", "default": ""},
                "source_scope": {"type": "string", "enum": ["enterprise", "personal"], "default": "enterprise"},
            },
            "required": ["page_id"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        context = self._scope(kwargs.get("source_scope"))
        if context is None:
            return {"error": "wiki_context_unavailable", "sources": [], "citation_authority": False}
        scope, owner, kb = context
        values = self.store.read_sources(
            str(kwargs.get("page_id") or ""), claim_id=str(kwargs.get("claim_id") or ""),
            source_scope=scope, owner_id=owner, knowledge_base_id=kb,
        )
        sources = [{
            key: value for key, value in item.items()
            if key in {"claim_id", "document_id", "document_version_id", "section_id", "evidence_id"}
        } for item in values]
        return {"sources": sources, "citation_authority": False}


class WikiSearchEvidenceTool(_ScopedWikiTool):
    """Return to authoritative RAG Evidence using Wiki-derived document priors."""

    def __init__(
        self,
        store: WikiStore,
        search_tool: SearchTool,
        library_tool: SearchLibraryTool | None = None,
        *,
        enterprise_knowledge_base_id: str = "",
    ) -> None:
        super().__init__(store, enterprise_knowledge_base_id=enterprise_knowledge_base_id)
        self.search_tool = search_tool
        self.library_tool = library_tool

    @property
    def name(self) -> str:
        return "wiki_search_evidence"

    @property
    def description(self) -> str:
        return (
            "Resolve an authorized Wiki page or claim to source documents, then run the normal "
            "BM25/vector Evidence retriever inside those documents. Returned Evidence may be cited."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "page_id": {"type": "string"},
                "claim_id": {"type": "string", "default": ""},
                "source_scope": {
                    "type": "string", "enum": ["enterprise", "personal"],
                    "default": "enterprise",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                "mode": {
                    "type": "string", "enum": ["hybrid", "vector", "bm25"],
                    "default": "hybrid",
                },
            },
            "required": ["query", "page_id"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        context = self._scope(kwargs.get("source_scope"))
        if context is None:
            return {
                "error": "wiki_context_unavailable", "items": [],
                "citation_authority": True,
            }
        scope, owner, kb = context
        sources = self.store.read_sources(
            str(kwargs.get("page_id") or ""),
            claim_id=str(kwargs.get("claim_id") or ""),
            source_scope=scope,
            owner_id=owner,
            knowledge_base_id=kb,
        )
        document_ids = list(dict.fromkeys(
            str(item.get("document_id") or "") for item in sources
            if str(item.get("document_id") or "")
        ))[:100]
        if not document_ids:
            return {"items": [], "source_documents": 0, "citation_authority": True}
        allowed_versions: dict[str, set[str]] = {}
        for source in sources:
            document_id = str(source.get("document_id") or "")
            version_id = str(source.get("document_version_id") or "")
            if document_id in document_ids and version_id:
                allowed_versions.setdefault(document_id, set()).add(version_id)

        def current_source(item: dict[str, Any]) -> bool:
            document_id = str(item.get("document_id") or item.get("doc_id") or "")
            version_id = str(item.get("version_id") or "")
            returned_scope = str(item.get("source_scope") or scope)
            return (returned_scope == scope and bool(version_id)
                    and version_id in allowed_versions.get(document_id, set()))

        query = str(kwargs.get("query") or "").strip()
        top_k = min(20, max(1, int(kwargs.get("top_k", 10))))
        mode = str(kwargs.get("mode") or "hybrid")
        if scope == "personal":
            if self.library_tool is None:
                return {
                    "error": "personal_library_unavailable", "items": [],
                    "citation_authority": True,
                }
            result = self.library_tool.execute(
                query=query, top_k=top_k, mode=mode, doc_ids=document_ids,
            )
            if not isinstance(result, dict):
                raise ValueError("personal library search must return an object")
            items = [item for item in result.get("items") or []
                     if isinstance(item, dict) and current_source(item)]
            return {
                **result,
                "items": items,
                "source_documents": len(document_ids),
                "citation_authority": True,
            }

        rows = self.search_tool.search(
            query=query,
            top_k=top_k,
            mode=mode,
            filters={"doc_ids": document_ids},
        )
        items = []
        for value in rows:
            if not isinstance(value, dict) or not current_source(value):
                continue
            item = dict(value)
            item["source_scope"] = "enterprise"
            item["document_id"] = str(item.get("document_id") or item.get("doc_id") or "")
            item["knowledge_base_id"] = str(item.get("knowledge_base_id") or kb)
            items.append(item)
        return {
            "items": items,
            "source_documents": len(document_ids),
            "citation_authority": True,
        }
