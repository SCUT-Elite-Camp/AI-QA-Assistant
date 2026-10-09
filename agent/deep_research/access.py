"""Live, fail-closed authorization shared by Research HTTP and workers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT_MODEL_ACCESS: ContextVar[Callable[[], None] | None] = ContextVar("research_model_access", default=None)


@contextmanager
def model_access_scope(check: Callable[[], None]) -> Iterator[None]:
    """Request/job-local permission checks; never mutable state on a renderer."""
    token = _CURRENT_MODEL_ACCESS.set(check)
    try:
        yield
    finally:
        _CURRENT_MODEL_ACCESS.reset(token)


def check_research_model_access() -> None:
    check = _CURRENT_MODEL_ACCESS.get()
    if check is not None:
        check()

from agent.schemas.research import (
    ResearchJob, ResearchReport, ResearchRequest, SourceManifest,
    SourceManifestDocument, SourceScope,
)
from agent.service.permission_service import PermissionResolutionError, PermissionService
from deep_research.manifest import SourceResolver


class ResearchAccessError(RuntimeError):
    def __init__(self, code: str, status_code: int = 403) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class ResearchAccessPolicy:
    """Resolve ACL on every use; a frozen source manifest is not an ACL grant."""

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self.permission_service = permission_service or PermissionService()

    def accessible_doc_ids(self, user_id: str, doc_ids: list[str] | None = None) -> set[str] | None:
        try:
            values = self.permission_service.get_accessible_doc_ids_strict(user_id, doc_ids=doc_ids)
        except PermissionResolutionError as exc:
            raise ResearchAccessError(exc.code, exc.status_code) from exc
        return None if values is None else set(values)

    def list_documents(self, user_id: str, resolver: SourceResolver) -> list[SourceManifestDocument]:
        allowed = self.accessible_doc_ids(user_id)
        return [item for item in resolver.list_documents() if allowed is None or item.doc_id in allowed]

    def authorize_request(
        self, request: ResearchRequest, user_id: str, resolver: SourceResolver,
    ) -> ResearchRequest:
        """Freeze the authorized selector result into an explicit document list.

        Explicit unauthorized IDs reject the whole request. Broad KB/topic
        selectors expose only their authorized intersection, never a global list.
        """
        allowed = self.accessible_doc_ids(user_id)
        explicit = set(request.source_scope.document_ids)
        if allowed is not None and not explicit.issubset(allowed):
            raise ResearchAccessError("research_source_forbidden")
        manifest = resolver.resolve("authorization-preview", request.source_scope, allowed_doc_ids=allowed)
        document_ids = [
            item.doc_id for item in manifest.documents
            if allowed is None or item.doc_id in allowed
        ]
        if not document_ids:
            raise ResearchAccessError("research_source_forbidden")
        return request.model_copy(update={"source_scope": SourceScope(document_ids=document_ids)})

    def authorize_job(self, job: ResearchJob, manifest: SourceManifest | None = None) -> set[str]:
        """Recheck every frozen source, so revocation invalidates persisted output."""
        requested = set(job.request.source_scope.document_ids)
        if not requested:
            raise ResearchAccessError("research_scope_not_authorized")
        frozen = {item.doc_id for item in manifest.documents} if manifest else requested
        allowed = self.accessible_doc_ids(job.user_id, sorted(requested | frozen))
        if not frozen.issubset(requested):
            raise ResearchAccessError("research_manifest_scope_mismatch")
        if allowed is not None and not (requested | frozen).issubset(allowed):
            raise ResearchAccessError("research_source_access_revoked")
        if manifest is not None:
            from deep_research.manifest import LocalDocumentResolver
            for item in manifest.documents:
                document = self.permission_service.source_provider._load(item.doc_id)
                if document is None:
                    raise ResearchAccessError("research_source_access_revoked")
                current = LocalDocumentResolver._snapshot(item.doc_id, document)
                if current.content_hash != item.content_hash or current.version != item.version:
                    raise ResearchAccessError("document_version_changed", 409)
        return frozen

    def authorize_document(self, job: ResearchJob, manifest: SourceManifest, doc_id: str) -> None:
        frozen = self.authorize_job(job, manifest)
        if doc_id not in frozen:
            raise ResearchAccessError("research_document_not_found", 404)

    def validate_report(self, report: ResearchReport, job: ResearchJob, manifest: SourceManifest) -> None:
        frozen = self.authorize_job(job, manifest)
        if report.research_id != job.research_id or any(item.doc_id not in frozen for item in report.citations):
            raise ResearchAccessError("research_report_source_forbidden")
