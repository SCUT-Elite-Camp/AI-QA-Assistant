from __future__ import annotations

from typing import Any

from .base_tool import BaseTool
from .search_tool import SearchTool
from .search_library_tool import SearchLibraryTool


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
        if kwargs.get("source_scope") == "personal":
            if self.library_tool is None:
                return {"error": "personal_library_unavailable", "sections": []}
            return self.library_tool.browse_outline(**kwargs)
        sections = self.search_tool.browse_document_outline(
            str(kwargs.get("query") or ""),
            doc_ids=kwargs.get("doc_ids"),
            top_k=min(12, max(1, int(kwargs.get("top_k", 8)))),
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
        if kwargs.get("source_scope") == "personal":
            if self.library_tool is None:
                return {"error": "personal_library_unavailable", "items": []}
            return self.library_tool.search_evidence_in_scope(**kwargs)
        rows = self.search_tool.search_evidence_in_scope(
            str(kwargs.get("query") or ""),
            section_ids=list(kwargs.get("section_ids") or []),
            doc_ids=kwargs.get("doc_ids"),
            top_k=min(20, max(1, int(kwargs.get("top_k", 10)))),
            mode=str(kwargs.get("mode") or "hybrid"),
        )
        return {"items": rows, "citation_authority": True}
