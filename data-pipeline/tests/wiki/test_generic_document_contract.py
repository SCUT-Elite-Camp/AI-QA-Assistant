from __future__ import annotations

import hashlib

import pytest

from pipeline.wiki.domain import (
    WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope, WikiSourceChunk, WikiSourceDocument,
)
from pipeline.wiki.extraction import CandidateExtractor


class GenericExtractionFake:
    model = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["schema_name"] == "wiki_candidate_extraction":
            return {"candidates": [{
                "local_id": "topic", "kind": "CONCEPT", "name": "Rate limiting",
                "category": None, "aliases": [], "description": "Request rate control",
            }]}
        evidence = kwargs["user"]["evidence"][0]
        return {"bindings": [{
            "candidate_handle": kwargs["user"]["candidates"][0]["candidate_handle"],
            "substantive": True, "reason": "explained in source",
            "evidence_handles": [evidence["evidence_handle"]],
        }]}


def _document(doc_type: str, number: int) -> WikiSourceDocument:
    text = "Rate limiting controls request frequency and protects service capacity."
    evidence_id = f"ev-{doc_type}-{number}"
    chunk = WikiSourceChunk(
        evidence_id=evidence_id, text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(), ordinal=0,
    )
    knowledge = WikiKnowledgeChunk(
        id=f"kc-{doc_type}-{number}", text=text,
        source_spans=(WikiKnowledgeSpan(
            evidence_id=evidence_id, evidence_start=0, evidence_end=len(text),
            knowledge_start=0, knowledge_end=len(text),
        ),), ordinal=0,
    )
    return WikiSourceDocument(
        scope=WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
        document_id=f"doc-{doc_type}-{number}", document_version_id=f"ver-{doc_type}-{number}",
        title=f"{doc_type} {number}", doc_type=doc_type,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        chunks=(chunk,), knowledge_chunks=(knowledge,),
    )


@pytest.mark.parametrize("doc_type", [
    "technical-design", "project-report", "api-documentation",
    "tutorial", "faq", "low-structure-markdown",
])
@pytest.mark.parametrize("number", [1, 2])
def test_candidate_pipeline_is_not_conditioned_on_meeting_record_shape(doc_type: str, number: int) -> None:
    client = GenericExtractionFake()
    result = CandidateExtractor(client).extract(_document(doc_type, number))
    assert len(result.candidates) == 1 and result.candidates[0].sources
    instructions = "\n".join(str(call["system"]) for call in client.calls).casefold()
    assert "meeting" not in instructions
    assert "tao" not in instructions and "vincent" not in instructions
