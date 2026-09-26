"""Request-local handles for model-selected authoritative Evidence.

The model sees opaque handles and source text. Real Evidence identifiers and
provenance fields are resolved only by the backend after schema validation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .domain import (
    CandidateSource,
    WikiCandidate,
    WikiSourceChunk,
    WikiSourceDocument,
    source_reference_id,
)
from .source import validate_candidate_source


class InvalidCitationHandle(ValueError):
    """Raised when a model returns an unknown, duplicate, or malformed handle."""


@dataclass(frozen=True)
class BindingHandleRegistry:
    """A non-persistent handle registry scoped to one binding request."""

    document: WikiSourceDocument
    candidates_by_handle: dict[str, WikiCandidate]
    candidate_handles_by_id: dict[str, str]
    evidence_by_handle: dict[str, WikiSourceChunk]
    evidence_handles_by_id: dict[str, str]

    @classmethod
    def create(
        cls,
        document: WikiSourceDocument,
        candidates: list[WikiCandidate],
        evidence: tuple[WikiSourceChunk, ...],
    ) -> "BindingHandleRegistry":
        if not candidates or not evidence:
            raise ValueError("binding handles require candidates and Evidence")
        if any(candidate.scope != document.scope for candidate in candidates):
            raise ValueError("binding candidates must share the document scope")

        material = "\n".join([
            document.scope.source_scope,
            document.scope.owner_id,
            document.scope.knowledge_base_id,
            document.document_version_id,
            *(f"candidate:{candidate.id}" for candidate in candidates),
            *(f"evidence:{chunk.evidence_id}:{chunk.text_sha256}" for chunk in evidence),
        ])
        namespace = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        candidate_handles_by_id = {
            candidate.id: f"k_{namespace}_{index:03d}"
            for index, candidate in enumerate(candidates, 1)
        }
        evidence_handles_by_id = {
            chunk.evidence_id: f"e_{namespace}_{index:03d}"
            for index, chunk in enumerate(evidence, 1)
        }
        return cls(
            document=document,
            candidates_by_handle={
                candidate_handles_by_id[candidate.id]: candidate for candidate in candidates
            },
            candidate_handles_by_id=candidate_handles_by_id,
            evidence_by_handle={
                evidence_handles_by_id[chunk.evidence_id]: chunk for chunk in evidence
            },
            evidence_handles_by_id=evidence_handles_by_id,
        )

    def candidate_payload(self, candidate: WikiCandidate) -> dict[str, object]:
        handle = self.candidate_handles_by_id.get(candidate.id)
        if handle is None:
            raise InvalidCitationHandle("candidate is outside the current handle scope")
        return {
            "candidate_handle": handle,
            "kind": candidate.kind.value,
            "name": candidate.name,
            "category": candidate.category.value if candidate.category else None,
            "aliases": candidate.aliases,
            "description": candidate.description,
        }

    def evidence_payload(self, chunk: WikiSourceChunk) -> dict[str, object]:
        handle = self.evidence_handles_by_id.get(chunk.evidence_id)
        if handle is None:
            raise InvalidCitationHandle("Evidence is outside the current handle scope")
        return {
            "evidence_handle": handle,
            "section_heading_path": list(chunk.heading_path),
            "text": chunk.text,
        }

    def resolve_candidate(self, handle: object) -> WikiCandidate:
        if not isinstance(handle, str) or handle not in self.candidates_by_handle:
            raise InvalidCitationHandle("unknown or cross-request candidate handle")
        return self.candidates_by_handle[handle]

    def resolve_sources(self, handles: object) -> list[CandidateSource]:
        if not isinstance(handles, list) or any(not isinstance(handle, str) for handle in handles):
            raise InvalidCitationHandle("evidence_handles must be a list of strings")
        if len(handles) != len(set(handles)):
            raise InvalidCitationHandle("duplicate Evidence handle")
        sources: list[CandidateSource] = []
        for handle in handles:
            chunk = self.evidence_by_handle.get(handle)
            if chunk is None:
                raise InvalidCitationHandle("unknown or cross-request Evidence handle")
            source = CandidateSource(
                document_id=self.document.document_id,
                document_version_id=self.document.document_version_id,
                evidence_id=chunk.evidence_id,
                section_id=chunk.section_id,
                support_quote=chunk.text,
                quote_start=0,
                quote_end=len(chunk.text),
                evidence_sha256=chunk.text_sha256,
            )
            validate_candidate_source(source, [self.document])
            sources.append(source)
        return sources


@dataclass(frozen=True)
class PageSourceHandleRegistry:
    """Opaque source handles shared by every Map/Reduce call for one page."""

    sources_by_handle: dict[str, CandidateSource]
    handles_by_source_id: dict[str, str]

    @classmethod
    def create(
        cls, target_id: str, sources: list[CandidateSource],
    ) -> "PageSourceHandleRegistry":
        if not sources:
            raise ValueError("Wiki page handles require at least one source")
        source_ids = [source_reference_id(source) for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Wiki page sources must be unique")
        material = "\n".join([
            target_id,
            *(f"{source_id}:{source.evidence_sha256}" for source_id, source in zip(source_ids, sources)),
        ])
        namespace = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        handles_by_source_id = {
            source_id: f"s_{namespace}_{index:04d}"
            for index, source_id in enumerate(source_ids, 1)
        }
        return cls(
            sources_by_handle={
                handles_by_source_id[source_id]: source
                for source_id, source in zip(source_ids, sources)
            },
            handles_by_source_id=handles_by_source_id,
        )

    def source_payload(self, source: CandidateSource) -> dict[str, object]:
        source_id = source_reference_id(source)
        handle = self.handles_by_source_id.get(source_id)
        if handle is None:
            raise InvalidCitationHandle("page source is outside the current handle scope")
        return {
            "source_handle": handle,
            "section_id": source.section_id,
            "text": source.support_quote,
        }

    def resolve_source_ids(
        self, handles: object, *, allowed: set[str] | None = None,
        allow_empty: bool = False,
    ) -> list[str]:
        if handles == [] and allow_empty:
            return []
        if not isinstance(handles, list) or not handles or any(not isinstance(handle, str) for handle in handles):
            raise InvalidCitationHandle("source_handles must be a non-empty list of strings")
        if len(handles) != len(set(handles)):
            raise InvalidCitationHandle("duplicate page source handle")
        if allowed is not None and not set(handles) <= allowed:
            raise InvalidCitationHandle("page source handle is outside the current Map batch")
        try:
            return [source_reference_id(self.sources_by_handle[handle]) for handle in handles]
        except KeyError as exc:
            raise InvalidCitationHandle("unknown or cross-request page source handle") from exc
