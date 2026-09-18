from __future__ import annotations

import hashlib

from pipeline.wiki.domain import (
    CandidateKind, CandidateSource, CandidateStatus, WikiCandidate, WikiIdentity,
    WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope, WikiSourceChunk,
    WikiSourceDocument, source_reference_id,
)
from pipeline.wiki.page import WikiPageCompiler


class MapReduceFake:
    model = "fake"

    def __init__(self) -> None:
        self.map_batches: list[list[str]] = []

    def complete(self, **kwargs):
        if kwargs["schema_name"] == "wiki_page_claim_map":
            handles = [item["source_handle"] for item in kwargs["user"]["sources"]]
            self.map_batches.append(handles)
            return {"claims": [{
                "heading": "Evidence",
                "text": f"Atomic claim {handle}",
                "source_handles": [handle],
            } for handle in handles]}
        if kwargs["schema_name"] == "wiki_page_claim_reduce":
            claims = kwargs["user"]["atomic_claims"]
            return {"summary": "Grounded summary", "sections": [{
                "heading": "Evidence",
                "claims": [{
                    "text": item["text"],
                    "source_handles": item["source_handles"],
                } for item in claims],
            }]}
        raise AssertionError(kwargs["schema_name"])


def _inputs():
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    chunks = []
    knowledge = []
    sources = []
    for index in range(3):
        text = f"Evidence {index}: " + (chr(65 + index) * 1850)
        evidence_id = f"ev-{index}"
        digest = hashlib.sha256(text.encode()).hexdigest()
        chunks.append(WikiSourceChunk(
            evidence_id=evidence_id, section_id=f"sec-{index}", text=text,
            text_sha256=digest, ordinal=index,
        ))
        knowledge.append(WikiKnowledgeChunk(
            id=f"kc-{index}", section_id=f"sec-{index}", text=text,
            source_spans=(WikiKnowledgeSpan(
                evidence_id=evidence_id, evidence_start=0, evidence_end=len(text),
                knowledge_start=0, knowledge_end=len(text),
            ),), ordinal=index,
        ))
        sources.append(CandidateSource(
            document_id="doc", document_version_id="ver", evidence_id=evidence_id,
            section_id=f"sec-{index}", support_quote=text, quote_start=0,
            quote_end=len(text), evidence_sha256=digest,
        ))
    document = WikiSourceDocument(
        scope=scope, document_id="doc", document_version_id="ver", title="Long source",
        content_sha256=hashlib.sha256("all".encode()).hexdigest(), chunks=tuple(chunks),
        knowledge_chunks=tuple(knowledge),
    )
    candidate = WikiCandidate(
        id="candidate", scope=scope, kind=CandidateKind.CONCEPT, name="Long topic",
        document_ids=["doc"], sources=sources, status=CandidateStatus.EVIDENCE_BOUND,
        input_hash="hash",
    )
    identity = WikiIdentity(
        id="identity", scope=scope, kind=CandidateKind.CONCEPT,
        canonical_name="Long topic", slug="long-topic-identity",
        candidate_ids=[candidate.id],
        source_ids=[source_reference_id(source) for source in sources],
    )
    return document, candidate, identity


def test_map_reduce_processes_every_source_batch_without_tail_truncation() -> None:
    document, candidate, identity = _inputs()
    client = MapReduceFake()
    pages = WikiPageCompiler(client, max_source_chars=2000).compile(
        [document], [candidate], [identity], [], [],
    )
    identity_page = next(page for page in pages if page.identity_id == identity.id)
    cited = {
        source_id for section in identity_page.sections for claim in section.claims
        for source_id in claim.source_ids
    }
    assert len(client.map_batches) == 6  # three identity batches plus three summary batches
    assert all(len(batch) == 1 for batch in client.map_batches)
    assert cited == set(identity.source_ids)
    assert identity_page.links == []
