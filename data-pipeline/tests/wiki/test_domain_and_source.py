from __future__ import annotations

import hashlib

import pytest

from models.document import Chunk, Document, DocumentSection
from pipeline.wiki.domain import CandidateSource, WikiScope, WikiSourceChunk
from pipeline.wiki.source import document_to_wiki_source, validate_candidate_source


def _document(*, active: bool = True) -> Document:
    return Document(
        doc_id="doc-1", version_id="ver-1", title="Architecture Notes",
        content="RAG uses retrieval.", space="docs", address="/not/read.md",
        last_updated="2026-01-01", source_url="https://example.test/doc-1",
        active_version=active,
        chunks=[Chunk(index=0, chunk_id="ev-1", text="RAG uses retrieval.", section_path=["Overview"])],
        sections=[DocumentSection(
            id="sec-1", version_id="ver-1", title="Overview", evidence_ids=["ev-1"],
        )],
    )


def test_document_adapter_preserves_version_section_and_evidence_hash() -> None:
    source = document_to_wiki_source(
        _document(), WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
    )
    assert source.document_version_id == "ver-1"
    assert source.chunks[0].section_id == "sec-1"
    assert source.chunks[0].text_sha256 == hashlib.sha256(b"RAG uses retrieval.").hexdigest()


def test_source_contract_rejects_stale_versions_and_inexact_quotes() -> None:
    with pytest.raises(ValueError, match="stale"):
        document_to_wiki_source(
            _document(active=False), WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
        )
    source = document_to_wiki_source(
        _document(), WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
    )
    bad = CandidateSource(
        document_id="doc-1", document_version_id="ver-1", evidence_id="ev-1",
        section_id="sec-1", support_quote="RAG uses search.", quote_start=0,
        quote_end=16, evidence_sha256=source.chunks[0].text_sha256,
    )
    with pytest.raises(ValueError, match="exact Evidence span"):
        validate_candidate_source(bad, [source])


def test_source_models_import_without_local_files_and_verify_hashes() -> None:
    with pytest.raises(ValueError, match="hash"):
        WikiSourceChunk(
            evidence_id="ev", text="content", text_sha256="0" * 64, ordinal=0,
        )
