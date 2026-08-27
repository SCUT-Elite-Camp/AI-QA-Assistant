"""SourceManifest resolution for the Local Deep Research control plane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from agent.schemas.research import SourceManifest, SourceManifestDocument, SourceScope


class ManifestResolutionError(ValueError):
    """A requested local source cannot be frozen into a manifest."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SourceResolver(Protocol):
    def resolve(self, research_id: str, scope: SourceScope) -> SourceManifest:
        """Resolve an explicit local scope into an immutable manifest."""


class LocalDocumentResolver:
    """Resolve source metadata from the repository's processed JSON documents.

    The resolver only reads the local document catalog.  It never follows a
    URL, and it never adds a document after the manifest has been returned.
    """

    def __init__(self, documents_dir: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.documents_dir = Path(documents_dir) if documents_dir else (
            project_root / "data-persistence" / "data" / "documents"
        )
        self.documents_dir = self.documents_dir.resolve()

    def resolve(self, research_id: str, scope: SourceScope) -> SourceManifest:
        if not scope.has_explicit_scope():
            raise ManifestResolutionError(
                "research_source_scope_required",
                "source scope must name a local knowledge base, document, or topic",
            )
        if not self.documents_dir.is_dir():
            raise ManifestResolutionError(
                "source_manifest_catalog_unavailable",
                f"local document catalog does not exist: {self.documents_dir}",
            )

        records = self._load_catalog()
        selected: dict[str, dict[str, Any]] = {}

        for doc_id in scope.document_ids:
            record = records.get(doc_id)
            if record is None:
                raise ManifestResolutionError(
                    "source_manifest_document_not_found",
                    f"document '{doc_id}' is not present in the local catalog",
                )
            selected[doc_id] = record

        knowledge_base_ids = set(scope.knowledge_base_ids)
        topic = scope.topic.casefold()
        for doc_id, record in records.items():
            if knowledge_base_ids and str(record.get("space", "")) not in knowledge_base_ids:
                continue
            if topic and topic not in self._searchable_text(record).casefold():
                continue
            if knowledge_base_ids or topic:
                selected[doc_id] = record

        if not selected:
            raise ManifestResolutionError(
                "source_manifest_no_matching_documents",
                "the explicit local source scope matched no documents",
            )

        documents = [self._snapshot(doc_id, record) for doc_id, record in selected.items()]
        return SourceManifest.from_documents(research_id, documents)

    def _load_catalog(self) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        for path in sorted(self.documents_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            doc_id = str(payload.get("doc_id") or path.stem)
            catalog[doc_id] = payload
        return catalog

    @staticmethod
    def _searchable_text(record: dict[str, Any]) -> str:
        chunks = record.get("chunks") or []
        chunk_text = " ".join(
            str(chunk.get("text") or chunk.get("chunk_text") or "")
            for chunk in chunks
            if isinstance(chunk, dict)
        )
        return " ".join(
            str(value)
            for value in (record.get("title", ""), record.get("content", ""), chunk_text)
        )

    @staticmethod
    def _snapshot(doc_id: str, record: dict[str, Any]) -> SourceManifestDocument:
        content = LocalDocumentResolver._searchable_text(record)
        raw_hash = record.get("content_hash")
        content_hash = str(raw_hash) if raw_hash else hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()
        version = record.get("version") or record.get("last_updated")
        return SourceManifestDocument(
            doc_id=doc_id,
            version=str(version) if version is not None else None,
            content_hash=content_hash,
        )


class InMemoryDocumentResolver:
    """Deterministic resolver used by control-plane tests and local demos."""

    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = dict(documents)

    def resolve(self, research_id: str, scope: SourceScope) -> SourceManifest:
        selected: dict[str, dict[str, Any]] = {}
        for doc_id in scope.document_ids:
            if doc_id not in self.documents:
                raise ManifestResolutionError(
                    "source_manifest_document_not_found",
                    f"document '{doc_id}' is not present in the in-memory catalog",
                )
            selected[doc_id] = self.documents[doc_id]

        topic = scope.topic.casefold()
        knowledge_base_ids = set(scope.knowledge_base_ids)
        for doc_id, record in self.documents.items():
            searchable = LocalDocumentResolver._searchable_text(record).casefold()
            if topic and topic not in searchable:
                continue
            if knowledge_base_ids and str(record.get("space", "")) not in knowledge_base_ids:
                continue
            if topic or knowledge_base_ids:
                selected[doc_id] = record

        if not selected:
            raise ManifestResolutionError(
                "source_manifest_no_matching_documents",
                "the explicit local source scope matched no documents",
            )

        return SourceManifest.from_documents(
            research_id,
            [LocalDocumentResolver._snapshot(doc_id, record) for doc_id, record in selected.items()],
        )


__all__ = [
    "InMemoryDocumentResolver",
    "LocalDocumentResolver",
    "ManifestResolutionError",
    "SourceResolver",
]
