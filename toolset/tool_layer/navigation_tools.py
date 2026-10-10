from __future__ import annotations

from typing import Any

from .base_tool import BaseTool
from .search_tool import SearchTool
from .search_library_tool import SearchLibraryTool


_MAX_DOCUMENT_IDS = 100
_MAX_SECTION_IDS = 20
_SOURCE_SCOPES = frozenset({"enterprise", "personal"})
_SEARCH_MODES = frozenset({"hybrid", "vector", "bm25"})


def _valid_id_list(value: Any, *, minimum: int = 0, maximum: int) -> bool:
    return (
        isinstance(value, list)
        and minimum <= len(value) <= maximum
        and all(isinstance(item, str) for item in value)
    )


def _valid_top_k(value: Any, *, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= maximum:
        return None
    return value


class BrowseDocumentOutlineTool(BaseTool):
    def __init__(
        self,
        search_tool: SearchTool,
        library_tool: SearchLibraryTool | None = None,
    ) -> None:
        self.search_tool = search_tool
        self.library_tool = library_tool

    @property
    def name(self) -> str:
        return "browse_document_outline"

    @property
    def description(self) -> str:
        return (
            "Search authorized document outlines after Direct Evidence is incomplete. "
            "Returns Section IDs, paths, and summaries for navigation only; not citations."
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
                "doc_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 12, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        source_scope = kwargs.get("source_scope", "enterprise")
        if type(source_scope) is not str or source_scope not in _SOURCE_SCOPES:
            return {
                "error": "invalid_navigation_query",
                "sections": [],
                "citation_authority": False,
            }
        query = kwargs.get("query")
        if type(query) is not str or not query.strip():
            return {
                "error": "invalid_navigation_query",
                "sections": [],
                "citation_authority": False,
            }
        if source_scope == "personal":
            if self.library_tool is None:
                return {"error": "personal_library_unavailable", "sections": []}
            return self.library_tool.browse_outline(**kwargs)
        doc_ids = kwargs.get("doc_ids")
        if doc_ids is not None and not _valid_id_list(
            doc_ids, maximum=_MAX_DOCUMENT_IDS
        ):
            return {
                "error": "invalid_navigation_query",
                "sections": [],
                "citation_authority": False,
            }
        top_k = _valid_top_k(kwargs.get("top_k", 8), maximum=12)
        if top_k is None:
            return {
                "error": "invalid_navigation_query",
                "sections": [],
                "citation_authority": False,
            }
        sections = self.search_tool.browse_document_outline(
            query,
            doc_ids=doc_ids,
            top_k=top_k,
        )
        return {"sections": sections, "citation_authority": False}


class SearchEvidenceInScopeTool(BaseTool):
    def __init__(
        self,
        search_tool: SearchTool,
        library_tool: SearchLibraryTool | None = None,
    ) -> None:
        self.search_tool = search_tool
        self.library_tool = library_tool

    @property
    def name(self) -> str:
        return "search_evidence_in_scope"

    @property
    def description(self) -> str:
        return (
            "Retrieve authoritative Evidence inside selected authorized Section IDs. "
            "Call after browse_document_outline; returned chunks may be cited."
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
                "section_ids": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": 20,
                },
                "doc_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                "mode": {"type": "string", "enum": ["hybrid", "vector", "bm25"], "default": "hybrid"},
            },
            "required": ["query", "section_ids"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        source_scope = kwargs.get("source_scope", "enterprise")
        if type(source_scope) is not str or source_scope not in _SOURCE_SCOPES:
            return {
                "error": "invalid_navigation_query",
                "items": [],
                "citation_authority": True,
            }
        query = kwargs.get("query")
        if type(query) is not str or not query.strip():
            return {
                "error": "invalid_navigation_query",
                "items": [],
                "citation_authority": True,
            }
        mode = kwargs.get("mode", "hybrid")
        if type(mode) is not str or mode not in _SEARCH_MODES:
            return {
                "error": "invalid_navigation_query",
                "items": [],
                "citation_authority": True,
            }
        if source_scope == "personal":
            if self.library_tool is None:
                return {"error": "personal_library_unavailable", "items": []}
            return self.library_tool.search_evidence_in_scope(
                **{**kwargs, "query": query, "mode": mode}
            )
        section_ids = kwargs.get("section_ids")
        doc_ids = kwargs.get("doc_ids")
        if (
            not _valid_id_list(
                section_ids, minimum=1, maximum=_MAX_SECTION_IDS
            )
            or (doc_ids is not None and not _valid_id_list(
                doc_ids, maximum=_MAX_DOCUMENT_IDS
            ))
        ):
            return {
                "error": "invalid_navigation_query",
                "items": [],
                "citation_authority": True,
            }
        top_k = _valid_top_k(kwargs.get("top_k", 10), maximum=20)
        if top_k is None:
            return {
                "error": "invalid_navigation_query",
                "items": [],
                "citation_authority": True,
            }
        rows = self.search_tool.search_evidence_in_scope(
            query,
            section_ids=section_ids,
            doc_ids=doc_ids,
            top_k=top_k,
            mode=mode,
        )
        return {"items": rows, "citation_authority": True}
