"""Agent-facing document catalog and batch full-text reading tools."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from data_persistence.vector import matches_filters, normalize_filters

from .base_tool import BaseTool
from .evidence_metadata import chunk_metadata, source_metadata


_DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.:-]+")
_PUBLIC_FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})


def _normalize_public_filters(filters: Any) -> dict:
    if isinstance(filters, dict):
        unknown = set(filters) - _PUBLIC_FILTER_KEYS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported filter keys: {names}")
        if "doc_id" in filters and not isinstance(filters["doc_id"], str):
            raise ValueError("doc_id must be a string")
        if "doc_ids" in filters and not isinstance(filters["doc_ids"], list):
            raise ValueError("doc_ids must be an array")
    return normalize_filters(filters)


def _document_type(document: dict) -> str:
    value = document.get("doc_type")
    metadata = document.get("metadata")
    if not value and isinstance(metadata, dict):
        value = metadata.get("doc_type") or metadata.get("content_type")
    fallback = Path(str(document.get("address", ""))).suffix
    candidate = str(value or "").strip().lower()
    if "/" in candidate:
        candidate = candidate.rsplit("/", 1)[-1]
    if not candidate or candidate in {"attachment", "page", "hybrid"}:
        candidate = fallback
    return candidate.removeprefix(".")


class DocumentRepository:
    """Read production document JSON files with path-boundary validation."""

    def __init__(self, documents_dir: Path) -> None:
        self.documents_dir = documents_dir.resolve()

    def load(self, doc_id: str) -> dict | None:
        if not isinstance(doc_id, str) or not _DOC_ID_PATTERN.fullmatch(doc_id):
            raise ValueError("invalid_doc_id")
        path = (self.documents_dir / f"{doc_id}.json").resolve()
        if path.parent != self.documents_dir:
            raise ValueError("invalid_doc_id")
        if not path.is_file():
            return None
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) and value.get("active_version", True) is True else None

    def list(self) -> list[dict]:
        if not self.documents_dir.is_dir():
            return []
        documents = []
        for path in sorted(self.documents_dir.glob("*.json")):
            try:
                document = self.load(path.stem)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if document is not None:
                document.setdefault("doc_id", path.stem)
                documents.append(document)
        return documents


class FindDocumentsTool(BaseTool):
    """Find documents by metadata and aggregated lexical chunk matches."""

    def __init__(self, search_tool) -> None:
        self.search_tool = search_tool
        self.repository = DocumentRepository(search_tool.documents_dir)

    @property
    def name(self) -> str:
        return "find_documents"

    @property
    def description(self) -> str:
        return (
            "Find or list documents by title, identifier, space, type, or content "
            "keywords. Omit query to browse the document catalog. Returns metadata "
            "for selecting documents, never citable evidence; use get_document to read them."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional title or content query.",
                    "maxLength": 512,
                },
                "filters": _filter_schema(),
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
            },
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> Any:
        query_value = kwargs.get("query", "")
        if type(query_value) is not str:
            raise ValueError("query must be a string")
        query = query_value.strip()
        filters = _normalize_public_filters(kwargs.get("filters"))
        top_k = kwargs.get("top_k", 5)
        offset = kwargs.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError("top_k must be an integer from 1 to 20")
        if len(query) > 512:
            raise ValueError("query must not exceed 512 characters")

        content_matches: dict[str, dict] = {}
        if query:
            try:
                hits = self.search_tool.bm25_index.search(
                    query,
                    top_k=max(top_k * 10, 50),
                    filters=filters,
                )
            except RuntimeError:
                hits = []
            maximum = max((float(hit.get("score", 0.0)) for hit in hits), default=0.0)
            for hit in hits:
                doc_id = str(hit.get("doc_id", ""))
                score = float(hit.get("score", 0.0)) / maximum if maximum > 0 else 0.0
                current = content_matches.get(doc_id)
                if current is None or score > current["score"]:
                    content_matches[doc_id] = {
                        "score": score,
                        "summary": str(hit.get("text", ""))[:300],
                    }

        rows = []
        normalized_query = query.casefold()
        for document in self.repository.list():
            metadata = {
                **source_metadata(document),
                "doc_id": str(document.get("doc_id", "")),
                "title": str(document.get("title", "")),
                "space": str(document.get("space", "")),
                "doc_type": _document_type(document),
                "last_updated": str(document.get("last_updated", "")),
                "source_url": str(document.get("source_url", "")),
                "read_status": "retrieval_hit",
            }
            if not matches_filters(metadata, filters):
                continue
            content = content_matches.get(metadata["doc_id"], {"score": 0.0, "summary": ""})
            exact_id = bool(query and normalized_query == metadata["doc_id"].casefold())
            title_score = _title_score(query, metadata["title"])
            if query and not exact_id and title_score == 0.0 and content["score"] == 0.0:
                continue
            score = 1.0 if exact_id else 0.6 * title_score + 0.4 * content["score"]
            rows.append({
                **metadata,
                "match_summary": content["summary"],
                "score": score,
                "exact_doc_id_match": exact_id,
            })

        rows.sort(key=lambda row: (
            -int(row["exact_doc_id_match"]),
            -row["score"],
            row["title"].casefold(),
            row["doc_id"],
        ))
        selected = rows[offset:offset + top_k]
        next_offset = offset + len(selected)
        return {
            "documents": selected, "result_count": len(selected),
            "total_documents": len(rows), "has_more": next_offset < len(rows),
            "next_offset": next_offset if next_offset < len(rows) else None,
        }


class GetDocumentTool(BaseTool):
    """Read the full parsed text and citation chunks of selected documents."""

    def __init__(self, documents_dir: Path) -> None:
        self.repository = DocumentRepository(documents_dir)

    @property
    def name(self) -> str:
        return "get_document"

    @property
    def description(self) -> str:
        return (
            "Read the complete parsed text of one or more documents in a single call. "
            "Choose doc_ids from search results or find_documents. Returns full content "
            "and source-bound chunks for citations, without pagination or silent truncation."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_ids": {
                    "type": "array", "minItems": 1, "maxItems": 20,
                    "items": {
                        "type": "string", "minLength": 1, "maxLength": 128,
                        "pattern": _DOC_ID_PATTERN.pattern,
                    },
                },
            },
            "required": ["doc_ids"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> Any:
        doc_ids = kwargs.get("doc_ids")
        if not isinstance(doc_ids, list) or not 1 <= len(doc_ids) <= 20:
            raise ValueError("doc_ids must contain 1 to 20 document IDs")
        if any(not isinstance(value, str) or not _DOC_ID_PATTERN.fullmatch(value) for value in doc_ids):
            raise ValueError("invalid_doc_id")
        documents, errors = [], []
        for doc_id in dict.fromkeys(doc_ids):
            document = self._read(doc_id)
            if document is None:
                errors.append({"doc_id": doc_id, "error": "document_not_found"})
            else:
                documents.append(document)
        return {"documents": documents, "errors": errors, "result_count": len(documents)}

    def _read(self, doc_id: str) -> dict | None:
        document = self.repository.load(doc_id)
        if document is None:
            return None
        document.setdefault("doc_id", doc_id)

        chunks = sorted(
            (chunk for chunk in document.get("chunks", []) if isinstance(chunk, dict)),
            key=lambda chunk: int(chunk.get("index", 0)),
        )
        content = document.get("content")
        if not isinstance(content, str) or not content:
            content = "\n\n".join(str(chunk.get("text") or chunk.get("chunk_text") or "") for chunk in chunks)
        if not chunks and content:
            chunks = [{"index": 0, "text": content}]
        return {
            **source_metadata(document),
            "doc_id": str(document.get("doc_id", doc_id)),
            "title": str(document.get("title", "")),
            "space": str(document.get("space", "")),
            "doc_type": _document_type(document),
            "last_updated": str(document.get("last_updated", "")),
            "source_url": str(document.get("source_url", "")),
            "content": content,
            "chunks": [{**chunk, **chunk_metadata(document, chunk)} for chunk in chunks],
        }


def _title_score(query: str, title: str) -> float:
    if not query:
        return 0.0
    query_key = query.casefold()
    title_key = title.casefold()
    if query_key == title_key:
        return 1.0
    if query_key in title_key or title_key in query_key:
        return 0.8
    query_tokens = set(_TOKEN_PATTERN.findall(query_key))
    title_tokens = set(_TOKEN_PATTERN.findall(title_key))
    if not query_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / len(query_tokens)


def _filter_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "doc_ids": {"type": "array", "items": {"type": "string"}},
            "space": {"type": "string"},
            "doc_type": {
                "type": "string",
                "description": "Normalized document type or file extension.",
            },
        },
        "additionalProperties": False,
    }
