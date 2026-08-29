"""Observation and Verified Evidence persistence boundary."""

from __future__ import annotations

import hashlib

from agent.schemas.research import Observation, VerifiedEvidence
from .repository import SQLiteResearchRepository
from .tools import OriginalRead, SearchHit, ToolCallContext


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:24]}"


class EvidenceLedger:
    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository

    def record_search(self, query: str, hits: list[SearchHit], context: ToolCallContext) -> list[Observation]:
        observations = []
        for hit in hits:
            item = Observation(
                observation_id=_id("obs", context.research_id, context.task_id, query, hit.doc_id, hit.locator_hint),
                research_id=context.research_id,
                task_id=context.task_id,
                tool_name="search",
                doc_id=hit.doc_id,
                locator_hint=hit.locator_hint,
                snippet=hit.snippet,
                query=query,
            )
            observations.append(self.repository.save_observation(item))
        return observations

    def record_original_read(self, read: OriginalRead, context: ToolCallContext) -> VerifiedEvidence:
        item = VerifiedEvidence(
            evidence_id=_id(
                "ev", context.research_id, context.task_id, read.doc_id, read.locator, read.content_hash
            ),
            research_id=context.research_id,
            task_id=context.task_id,
            doc_id=read.doc_id,
            document_version=read.document_version,
            locator=read.locator,
            excerpt=read.excerpt,
            content_hash=read.content_hash,
        )
        return self.repository.save_evidence(item)


__all__ = ["EvidenceLedger"]
