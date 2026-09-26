"""Reconcile authoritative enterprise document projections into Wiki jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models.document import Document
from storage.document_store import DOCS_DIR
from pipeline.confluence_snapshot import complete_confluence_export_pages

from .domain import WikiScope, WikiSourceDocument
from .queue import WikiLifecycleCoordinator
from .source import document_to_wiki_source


class WikiDocumentProjection:
    """Read only active, versioned Confluence documents from the RAG projection."""

    def __init__(
        self, documents_dir: str | Path = DOCS_DIR, *, knowledge_base_id: str = "default",
        confluence_export_dir: str | Path | None = None,
    ) -> None:
        if not knowledge_base_id.strip():
            raise ValueError("enterprise Wiki knowledge base ID is required")
        self.documents_dir = Path(documents_dir)
        self.knowledge_base_id = knowledge_base_id.strip()
        self.confluence_export_dir = Path(confluence_export_dir) if confluence_export_dir is not None else (
            Path(__file__).resolve().parents[3] / "data-persistence" / "data" / "raws" / "confluence"
        )

    def _complete_export_pages(self) -> dict[str, set[str]]:
        """Only successful full-space manifests can prove that a page disappeared."""
        return complete_confluence_export_pages(self.confluence_export_dir)

    def active_documents(self) -> dict[str, list[WikiSourceDocument]]:
        scopes: dict[str, list[WikiSourceDocument]] = {}
        complete_pages = self._complete_export_pages()
        for path in sorted(self.documents_dir.glob("*.json")):
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"invalid authoritative document projection: {path}")
            metadata = raw.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ValueError(f"invalid document metadata: {path}")
            space_id = str(metadata.get("space_id") or "").strip()
            if not space_id or not raw.get("active_version", True):
                continue
            page_id = str(metadata.get("page_id") or "").strip()
            if space_id in complete_pages:
                if not page_id:
                    raise ValueError(f"Confluence projection has no page ID: {path}")
                if page_id not in complete_pages[space_id]:
                    continue
            document = Document.model_validate(raw)
            if path.stem != document.doc_id:
                raise ValueError(f"document projection path and ID differ: {path}")
            scope = WikiScope(source_scope="enterprise", knowledge_base_id=self.knowledge_base_id)
            source = document_to_wiki_source(document, scope)
            scopes.setdefault(self.knowledge_base_id, []).append(source)
        for knowledge_base_id, documents in scopes.items():
            ids = [item.document_id for item in documents]
            if len(ids) != len(set(ids)):
                raise ValueError(f"multiple active versions in Wiki scope {knowledge_base_id}")
        return scopes


class WikiDocumentLifecycle:
    """Queue observed UPSERT/DELETE changes; a separate worker builds them."""

    def __init__(self, repository: Any, projection: WikiDocumentProjection) -> None:
        self.repository = repository
        self.projection = projection
        self.coordinator = WikiLifecycleCoordinator(repository)

    def _active_documents(self, *, reactivate: bool) -> dict[str, list[WikiSourceDocument]]:
        active_by_scope = self.projection.active_documents()
        confirmed_pages = (
            self.projection._complete_export_pages()
            if isinstance(self.projection, WikiDocumentProjection) else {}
        )
        visible: dict[str, list[WikiSourceDocument]] = {}
        for kb, documents in active_by_scope.items():
            context = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": kb}
            tombstones = self.repository.tombstoned_document_ids(**context)
            accepted = []
            for document in documents:
                if document.document_id in tombstones:
                    page_id = str(document.metadata.get("page_id") or "")
                    space_id = str(document.metadata.get("space_id") or "")
                    if not reactivate or page_id not in confirmed_pages.get(space_id, set()):
                        continue
                    self.repository.reactivate_wiki_source(**context, document_id=document.document_id)
                accepted.append(document)
            if accepted:
                visible[kb] = accepted
        return visible

    def reconcile(self) -> list[str]:
        active_by_scope = self._active_documents(reactivate=True)
        known_scopes = {
            kb for scope, owner, kb in self.repository.lifecycle_scopes()
            if scope == "enterprise" and not owner
            and kb == self.projection.knowledge_base_id
        }
        changed: list[str] = []
        for kb in sorted(set(active_by_scope) | known_scopes):
            scope = WikiScope(source_scope="enterprise", knowledge_base_id=kb)
            current = {item.document_id: item for item in active_by_scope.get(kb, [])}
            busy, observed = self.repository.lifecycle_observed_documents(
                source_scope="enterprise", owner_id="", knowledge_base_id=kb,
            )
            if busy:
                continue
            for document_id, document in sorted(current.items()):
                if observed.get(document_id) != (document.document_version_id, document.content_sha256):
                    changed.append(self.coordinator.document_ingested(document))
            for document_id, (version_id, _digest) in sorted(observed.items()):
                if document_id not in current:
                    changed.append(self.coordinator.document_deleted(
                        scope=scope, document_id=document_id,
                        document_version_id=version_id,
                    ))
        return changed

    def load_for_lease(self, lease: dict[str, Any]) -> list[WikiSourceDocument]:
        if (lease["source_scope"] != "enterprise" or lease["owner_id"]
                or lease["knowledge_base_id"] != self.projection.knowledge_base_id):
            raise ValueError("enterprise Wiki projection cannot load a personal scope")
        return self._active_documents(reactivate=False).get(lease["knowledge_base_id"], [])
