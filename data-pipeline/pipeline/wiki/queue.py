"""Persistent Wiki job protocol shared by workers and storage adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol
import hashlib

from pydantic import BaseModel, ConfigDict, Field

from .domain import WikiScope, WikiSourceDocument


class WikiJobStage(StrEnum):
    EXTRACT = "EXTRACT"
    CITE = "CITE"
    PROMOTE = "PROMOTE"
    RESOLVE = "RESOLVE"
    COMPILE = "COMPILE"
    VERIFY = "VERIFY"
    FINALIZE = "FINALIZE"
    PUBLISH = "PUBLISH"


WIKI_JOB_STAGES = tuple(WikiJobStage)


class WikiJobLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    source_scope: str
    owner_id: str = ""
    knowledge_base_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: WikiJobStage
    attempt: int = Field(ge=1)
    lease_owner: str = Field(min_length=1)
    lease_expires_at: int = Field(gt=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class WikiQueueRepository(Protocol):
    def enqueue_wiki_job(self, **kwargs: Any) -> str: ...
    def lease_wiki_job(self, *, worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None: ...
    def advance_wiki_job(
        self, job_id: str, *, worker_id: str, next_stage: WikiJobStage | None,
    ) -> None: ...
    def fail_wiki_job(
        self, job_id: str, *, worker_id: str, error: str, retry_at: int,
    ) -> None: ...
    def upsert_pending_wiki_op(self, **kwargs: Any) -> str: ...
    def schedule_pending_wiki_jobs(self, **kwargs: Any) -> list[str]: ...


class WikiLifecycleCoordinator:
    """Record active-document changes without building or publishing in the ingest request."""

    def __init__(self, repository: WikiQueueRepository) -> None:
        self.repository = repository

    def document_ingested(self, document: WikiSourceDocument) -> str:
        return self.repository.upsert_pending_wiki_op(
            source_scope=document.scope.source_scope, owner_id=document.scope.owner_id,
            knowledge_base_id=document.scope.knowledge_base_id,
            document_id=document.document_id,
            document_version_id=document.document_version_id,
            content_sha256=document.content_sha256,
            operation="UPSERT",
        )

    def document_deleted(
        self, *, scope: WikiScope, document_id: str, document_version_id: str,
    ) -> str:
        if not document_id.strip() or not document_version_id.strip():
            raise ValueError("Wiki deletion requires document and version identity")
        tombstone = hashlib.sha256(
            f"{scope.source_scope}\n{scope.owner_id}\n{scope.knowledge_base_id}\n"
            f"{document_id}\n{document_version_id}\nDELETE".encode("utf-8")
        ).hexdigest()
        return self.repository.upsert_pending_wiki_op(
            source_scope=scope.source_scope, owner_id=scope.owner_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id, document_version_id=document_version_id,
            content_sha256=tombstone, operation="DELETE",
        )

    def schedule(self, *, debounce_seconds: int = 5, publish: bool = False) -> list[str]:
        return self.repository.schedule_pending_wiki_jobs(
            debounce_seconds=debounce_seconds,
            intent="PUBLISH" if publish else "PREVIEW",
        )


def next_wiki_stage(stage: WikiJobStage) -> WikiJobStage | None:
    index = WIKI_JOB_STAGES.index(stage)
    return WIKI_JOB_STAGES[index + 1] if index + 1 < len(WIKI_JOB_STAGES) else None
