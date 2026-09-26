from __future__ import annotations

import hashlib

import pytest

from pipeline.wiki.citation import BindingHandleRegistry, InvalidCitationHandle
from pipeline.wiki.domain import (
    CandidateKind,
    WikiCandidate,
    WikiKnowledgeChunk,
    WikiKnowledgeSpan,
    WikiScope,
    WikiSourceChunk,
    WikiSourceDocument,
)


def _source() -> WikiSourceDocument:
    text = "Retrieval-Augmented Generation (RAG) combines retrieval and generation."
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    chunk = WikiSourceChunk(
        evidence_id="ev-1",
        section_id="sec-1",
        heading_path=("Overview",),
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        ordinal=0,
    )
    knowledge = WikiKnowledgeChunk(
        id="kc-1",
        section_id="sec-1",
        heading_path=("Overview",),
        text=text,
        source_spans=(WikiKnowledgeSpan(
            evidence_id="ev-1",
            evidence_start=0,
            evidence_end=len(text),
            knowledge_start=0,
            knowledge_end=len(text),
        ),),
        ordinal=0,
    )
    return WikiSourceDocument(
        scope=scope,
        document_id="doc-1",
        document_version_id="ver-1",
        title="RAG Notes",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        chunks=(chunk,),
        knowledge_chunks=(knowledge,),
    )


def _candidate(candidate_id: str, source) -> WikiCandidate:
    return WikiCandidate(
        id=candidate_id,
        scope=source.scope,
        kind=CandidateKind.CONCEPT,
        name="Retrieval Augmented Generation",
        document_ids=[source.document_id],
        input_hash="input-hash",
    )


def test_handle_registry_hides_real_ids_and_derives_full_evidence_source() -> None:
    source = _source()
    candidate = _candidate("candidate-secret-id", source)
    registry = BindingHandleRegistry.create(source, [candidate], source.chunks)

    candidate_payload = registry.candidate_payload(candidate)
    evidence_payload = registry.evidence_payload(source.chunks[0])
    assert "candidate-secret-id" not in str(candidate_payload)
    assert "ev-1" not in str(evidence_payload)
    assert "text_sha256" not in evidence_payload

    resolved = registry.resolve_sources([evidence_payload["evidence_handle"]])
    assert resolved[0].evidence_id == "ev-1"
    assert resolved[0].support_quote == source.chunks[0].text
    assert resolved[0].quote_start == 0
    assert resolved[0].quote_end == len(source.chunks[0].text)


def test_handle_registry_rejects_unknown_duplicate_and_cross_batch_handles() -> None:
    source = _source()
    first = _candidate("candidate-1", source)
    second = _candidate("candidate-2", source)
    first_registry = BindingHandleRegistry.create(source, [first], source.chunks)
    second_registry = BindingHandleRegistry.create(source, [second], source.chunks)
    first_handle = first_registry.evidence_payload(source.chunks[0])["evidence_handle"]

    with pytest.raises(InvalidCitationHandle, match="unknown or cross-request"):
        second_registry.resolve_sources([first_handle])
    with pytest.raises(InvalidCitationHandle, match="duplicate"):
        first_registry.resolve_sources([first_handle, first_handle])
    with pytest.raises(InvalidCitationHandle, match="unknown or cross-request"):
        first_registry.resolve_sources(["e_unknown_001"])
