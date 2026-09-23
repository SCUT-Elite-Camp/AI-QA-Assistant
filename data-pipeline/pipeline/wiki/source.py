"""Adapters and provenance checks for authoritative source Evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from models.document import Document

from .domain import (
    CandidateSource, WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope,
    WikiSourceChunk, WikiSourceDocument,
)
from .chunker import build_wiki_chunks


def document_to_wiki_source(document: Document, scope: WikiScope) -> WikiSourceDocument:
    """Convert one active parsed document without reading local sidecar files."""
    if not document.doc_id or not document.version_id or not document.title.strip():
        raise ValueError("Wiki source requires document, version, and title identities")
    if not document.active_version:
        raise ValueError("stale document versions cannot enter a Wiki build")
    section_by_evidence: dict[str, str] = {}
    for section in document.sections:
        if section.version_id != document.version_id:
            continue
        for evidence_id in section.evidence_ids:
            section_by_evidence.setdefault(evidence_id, section.id)
    chunks = tuple(
        WikiSourceChunk(
            evidence_id=chunk.chunk_id,
            section_id=section_by_evidence.get(chunk.chunk_id, ""),
            heading_path=tuple(chunk.section_path),
            text=chunk.text,
            text_sha256=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            source_url=document.source_url,
            ordinal=chunk.index,
        )
        for chunk in sorted(document.chunks, key=lambda item: (item.index, item.chunk_id))
        if chunk.text.strip()
    )
    if not chunks:
        raise ValueError("Wiki source document has no authoritative Evidence")

    semantic_chunks = build_wiki_chunks(document)
    knowledge_chunks = tuple(
        WikiKnowledgeChunk(
            id=item.id,
            section_id=item.section_id,
            heading_path=tuple(item.heading_path),
            content_type=item.content_type,
            text=item.content,
            source_spans=tuple(WikiKnowledgeSpan(
                evidence_id=span.evidence_id,
                evidence_start=span.evidence_start,
                evidence_end=span.evidence_end,
                knowledge_start=span.chunk_start,
                knowledge_end=span.chunk_end,
            ) for span in item.source_spans),
            ordinal=index,
        )
        for index, item in enumerate(semantic_chunks)
    )
    if not knowledge_chunks:
        raise ValueError("Wiki source document has no semantic knowledge chunks")
    content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    metadata = {
        key: document.metadata[key]
        for key in ("space_id", "page_id", "version", "content_sha256", "parent_id")
        if key in document.metadata
    }
    return WikiSourceDocument(
        scope=scope,
        document_id=document.doc_id,
        document_version_id=document.version_id,
        title=document.title.strip(),
        source_url=document.source_url,
        doc_type=document.doc_type,
        active_version=True,
        content_sha256=content_hash,
        chunks=chunks,
        knowledge_chunks=knowledge_chunks,
        metadata=metadata,
    )


def validate_candidate_source(source: CandidateSource, documents: Iterable[WikiSourceDocument]) -> None:
    """Reject stale, cross-scope, missing, or inexact provenance before model use."""
    matches = [
        document for document in documents
        if document.document_id == source.document_id
        and document.document_version_id == source.document_version_id
    ]
    if len(matches) != 1:
        raise ValueError("candidate source references an unknown or duplicate document version")
    chunk = next(
        (item for item in matches[0].chunks if item.evidence_id == source.evidence_id),
        None,
    )
    if chunk is None:
        raise ValueError("candidate source references unknown Evidence")
    if chunk.text_sha256 != source.evidence_sha256:
        raise ValueError("candidate source Evidence hash is stale")
    if source.section_id and source.section_id != chunk.section_id:
        raise ValueError("candidate source Section does not own the Evidence")
    if source.quote_end > len(chunk.text):
        raise ValueError("candidate source quote range exceeds Evidence")
    if chunk.text[source.quote_start:source.quote_end] != source.support_quote:
        raise ValueError("candidate support quote is not an exact Evidence span")
