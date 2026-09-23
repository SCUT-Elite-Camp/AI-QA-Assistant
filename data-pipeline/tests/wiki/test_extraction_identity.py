from __future__ import annotations

import hashlib

from pipeline.wiki.domain import (
    CandidateKind, CandidateSource, CandidateStatus, EntityCategory,
    PromotionStatus,
    WikiCandidate, WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope,
    WikiSourceChunk, WikiSourceDocument,
)
from pipeline.wiki.extraction import CandidateExtractor, CandidatePromotionSelector
from pipeline.wiki.identity import IdentityResolver


def _source(text: str = "Retrieval-Augmented Generation (RAG) combines retrieval and generation.") -> WikiSourceDocument:
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    chunk = WikiSourceChunk(
        evidence_id="ev-1", section_id="sec-1", heading_path=("Overview",), text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(), ordinal=0,
    )
    knowledge = WikiKnowledgeChunk(
        id="kc-1", section_id="sec-1", heading_path=("Overview",), text=text,
        source_spans=(WikiKnowledgeSpan(
            evidence_id="ev-1", evidence_start=0, evidence_end=len(text),
            knowledge_start=0, knowledge_end=len(text),
        ),), ordinal=0,
    )
    return WikiSourceDocument(
        scope=scope, document_id="doc-1", document_version_id="ver-1", title="RAG Notes",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), chunks=(chunk,),
        knowledge_chunks=(knowledge,),
    )


class ExtractionFake:
    model = "fake"

    def __init__(self, *, invalid_handle: bool = False, duplicate_handle: bool = False) -> None:
        self.invalid_handle = invalid_handle
        self.duplicate_handle = duplicate_handle
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["schema_name"] == "wiki_candidate_extraction":
            return {"candidates": [{
                "local_id": "c1", "kind": "CONCEPT", "name": "RAG", "category": None,
                "aliases": ["Retrieval-Augmented Generation"], "description": "A retrieval method",
            }]}
        if kwargs["schema_name"] == "wiki_candidate_evidence_binding":
            evidence = kwargs["user"]["evidence"][0]
            handle = evidence["evidence_handle"]
            return {"bindings": [{
                "candidate_handle": kwargs["user"]["candidates"][0]["candidate_handle"],
                "substantive": True, "reason": "Defined in source",
                "evidence_handles": (
                    [handle, handle] if self.duplicate_handle else
                    ["e_other_request_001"] if self.invalid_handle else [handle]
                ),
            }]}
        raise AssertionError(kwargs["schema_name"])


class IdentityFake:
    model = "fake"

    def __init__(self, action="MERGE") -> None:
        self.action = action
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["schema_name"] == "wiki_identity_type_conflict":
            return {"kind": "UNRESOLVED", "reason": "ambiguous referent"}
        target = kwargs["user"]["existing_identities"][0]["identity_id"]
        return {"action": self.action, "target_identity_id": target if self.action == "MERGE" else None,
                "reason": "same referent"}


class PromotionFake:
    model = "fake"

    def complete(self, **kwargs):
        return {"decisions": [{
            "candidate_id": item["candidate_id"],
            "promote": item["name"] == "RAG",
            "reason": "reusable concept" if item["name"] == "RAG" else "passing mention",
        } for item in kwargs["user"]["candidates"]]}


def test_two_pass_extraction_accepts_only_exact_evidence_binding() -> None:
    result = CandidateExtractor(ExtractionFake()).extract(_source())
    assert len(result.candidates) == 1
    assert result.candidates[0].status == CandidateStatus.EVIDENCE_BOUND
    assert result.candidates[0].sources[0].evidence_id == "ev-1"
    assert result.candidates[0].sources[0].quote_start == 0
    assert result.candidates[0].sources[0].quote_end == len(result.candidates[0].sources[0].support_quote)

    rejected = CandidateExtractor(ExtractionFake(invalid_handle=True)).extract(_source())
    assert rejected.candidates[0].status == CandidateStatus.REJECTED
    assert any(issue.code == "INVALID_EVIDENCE_BINDING" for issue in rejected.issues)

    duplicate = CandidateExtractor(ExtractionFake(duplicate_handle=True)).extract(_source())
    assert duplicate.candidates[0].status == CandidateStatus.REJECTED
    assert any("duplicate Evidence handle" in issue.message for issue in duplicate.issues)


def _candidate(candidate_id: str, kind: CandidateKind, name: str) -> WikiCandidate:
    source = _source()
    chunk = source.chunks[0]
    bound = CandidateSource(
        document_id=source.document_id, document_version_id=source.document_version_id,
        evidence_id=chunk.evidence_id, section_id=chunk.section_id,
        support_quote=chunk.text, quote_start=0, quote_end=len(chunk.text),
        evidence_sha256=chunk.text_sha256,
    )
    return WikiCandidate(
        id=candidate_id, scope=source.scope, kind=kind, name=name,
        category=EntityCategory.TECHNOLOGY if kind == CandidateKind.ENTITY else None,
        document_ids=[source.document_id], sources=[bound], status=CandidateStatus.EVIDENCE_BOUND,
        input_hash="hash",
    )


def test_identity_resolution_never_merges_related_cross_kind_candidates() -> None:
    client = IdentityFake()
    identities = IdentityResolver(client).resolve([
        _candidate("c1", CandidateKind.ENTITY, "RAG System"),
        _candidate("c2", CandidateKind.CONCEPT, "RAG"),
    ])
    assert len(identities) == 2
    assert client.calls == []


def test_identity_resolution_merges_aliases_but_keeps_immutable_id_and_slug() -> None:
    client = IdentityFake()
    first = IdentityResolver(client).resolve([_candidate("c1", CandidateKind.CONCEPT, "RAG")])
    identity_id, slug = first[0].id, first[0].slug
    second = _candidate("c2", CandidateKind.CONCEPT, "Retrieval Augmented Generation")
    merged = IdentityResolver(client).resolve([second], existing=first)
    assert len(merged) == 1
    assert merged[0].id == identity_id and merged[0].slug == slug
    assert "Retrieval Augmented Generation" in merged[0].aliases


def test_identity_resolution_quarantines_unresolved_cross_type_same_name() -> None:
    client = IdentityFake()
    identities, issues = IdentityResolver(client).resolve_with_issues([
        _candidate("c1", CandidateKind.ENTITY, "Agent Layer"),
        _candidate("c2", CandidateKind.CONCEPT, "agent layer"),
    ])
    assert identities == []
    assert len([issue for issue in issues if issue.code == "TYPE_CONFLICT_UNRESOLVED"]) == 2
    assert [call["schema_name"] for call in client.calls] == ["wiki_identity_type_conflict"]


def test_identity_resolution_sends_at_most_five_lexical_same_kind_targets() -> None:
    client = IdentityFake(action="NEW")
    resolver = IdentityResolver(client)
    base_candidates = [
        _candidate(f"base-{index}", CandidateKind.CONCEPT, f"Rate Limit {index}")
        for index in range(8)
    ]
    existing = [
        IdentityResolver(client).resolve([candidate])[0]
        for candidate in base_candidates
    ]
    client.calls.clear()
    resolver.resolve(
        [*base_candidates, _candidate("new", CandidateKind.CONCEPT, "Rate Limiting")],
        existing=existing,
    )
    decision = next(call for call in client.calls if call["schema_name"] == "wiki_identity_resolution")
    assert len(decision["user"]["existing_identities"]) <= 5
    assert all(item["kind"] == "CONCEPT" for item in decision["user"]["existing_identities"])


def test_candidate_promotion_is_explicit_and_only_promoted_candidates_become_identities() -> None:
    rag = _candidate("c1", CandidateKind.CONCEPT, "RAG")
    incidental = _candidate("c2", CandidateKind.ENTITY, "Incidental Name")
    candidates, issues = CandidatePromotionSelector(PromotionFake()).select([rag, incidental])

    assert not issues
    assert candidates[0].promotion_status == PromotionStatus.PROMOTED
    assert candidates[1].promotion_status == PromotionStatus.SKIPPED
    identities = IdentityResolver(IdentityFake()).resolve([
        item for item in candidates if item.promotion_status == PromotionStatus.PROMOTED
    ])
    assert [item.canonical_name for item in identities] == ["RAG"]


def test_candidate_promotion_requires_independent_confirmation() -> None:
    class Independent:
        model = "independent"

        def complete(self, **kwargs):
            return {"decisions": [{
                "candidate_id": item["candidate_id"], "promote": False,
                "reason": "only a passing mention",
            } for item in kwargs["user"]["candidates"]]}

    values, issues = CandidatePromotionSelector(
        PromotionFake(), confirmation_client=Independent(),
    ).select([_candidate("c1", CandidateKind.CONCEPT, "RAG")])
    assert values[0].promotion_status == PromotionStatus.SKIPPED
    assert any(issue.code == "PROMOTION_DISAGREEMENT" for issue in issues)


def test_latin_canonical_name_requires_exact_bound_evidence() -> None:
    candidate = _candidate("c1", CandidateKind.CONCEPT, "OtherWiki")
    candidate.aliases = ["RAG"]
    class AlwaysPromote:
        model = "always"

        def complete(self, **kwargs):
            return {"decisions": [{"candidate_id": candidate.id,
                                    "promote": True, "reason": "reusable"}]}

    values, issues = CandidatePromotionSelector(AlwaysPromote()).select([candidate])
    assert values[0].promotion_status == PromotionStatus.SKIPPED
    assert any(issue.code == "UNSUPPORTED_CANDIDATE_NAME" for issue in issues)


def test_extraction_configuration_is_explicit_and_limits_document_candidates() -> None:
    extractor = CandidateExtractor(
        ExtractionFake(),
        granularity="focused",
        target_language="en-US",
        max_candidates_per_document=1,
    )
    result = extractor.extract(_source())
    assert len(result.candidates) == 1
    extraction_call = next(
        call for call in extractor.client.calls
        if call["schema_name"] == "wiki_candidate_extraction"
    )
    assert extraction_call["user"]["document"]["granularity"] == "focused"
    assert extraction_call["user"]["document"]["target_language"] == "en-US"
