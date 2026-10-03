from __future__ import annotations

import hashlib

from pipeline.wiki.domain import (
    CandidateSource, RevisionStatus, WikiClaim, WikiPageDraft, WikiPageType,
    WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope, WikiSectionDraft,
    WikiSourceChunk, WikiSourceDocument, source_reference_id,
)
from pipeline.wiki.quality import WikiQualityGate


def _inputs():
    text = "The system uses retrieval."
    chunk = WikiSourceChunk(
        evidence_id="ev-1", section_id="sec-1", text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(), ordinal=0,
    )
    knowledge = WikiKnowledgeChunk(
        id="kc-1", section_id="sec-1", text=text,
        source_spans=(WikiKnowledgeSpan(
            evidence_id="ev-1", evidence_start=0, evidence_end=len(text),
            knowledge_start=0, knowledge_end=len(text),
        ),), ordinal=0,
    )
    document = WikiSourceDocument(
        scope=WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
        document_id="doc-1", document_version_id="ver-1", title="System",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), chunks=(chunk,),
        knowledge_chunks=(knowledge,),
    )
    source = CandidateSource(
        document_id="doc-1", document_version_id="ver-1", evidence_id="ev-1",
        section_id="sec-1", support_quote=text, quote_start=0, quote_end=len(text),
        evidence_sha256=chunk.text_sha256,
    )
    source_id = source_reference_id(source)
    page = WikiPageDraft(
        id="page-1", scope=document.scope, page_type=WikiPageType.SUMMARY,
        slug="system", title="System", input_hash="hash",
        sections=[WikiSectionDraft(heading="Overview", claims=[
            WikiClaim(id="claim-1", text="The system completed retrieval.", source_ids=[source_id]),
        ])],
    )
    return document, source_id, source, page


class AuditFake:
    model = "audit"

    def __init__(self):
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        claim = kwargs["user"]["claims"][0]
        supported = "completed" not in claim["text"]
        return {"claims": [{
            "claim_id": claim["claim_id"],
            "verdict": "SUPPORTED" if supported else "INSUFFICIENT",
            "reason_code": "ENTAILED" if supported else "OVERSTATED",
            "reason": "entailed" if supported else "the source does not establish completion",
            "source_handles": [claim["sources"][0]["source_handle"]],
        }]}


class RepairFake:
    model = "repair"

    def complete(self, **kwargs):
        claim = kwargs["user"]["claims"][0]
        return {"repairs": [{
            "claim_id": claim["claim_id"], "action": "REWRITE",
            "text": "The system uses retrieval.",
            "source_handles": [claim["sources"][0]["source_handle"]],
            "reason": "match source",
        }]}


def test_failed_claim_is_rewritten_then_reaudited_before_reviewing() -> None:
    document, source_id, source, page = _inputs()
    audit = AuditFake()
    result = WikiQualityGate(audit, RepairFake()).verify(page, {source_id: source}, [document])
    assert result.page.status == RevisionStatus.REVIEWING
    assert result.repair_rounds == 1 and audit.calls == 2
    assert result.page.sections[0].claims[0].text == "The system uses retrieval."
    assert [(item.audit_round, item.verdict.value) for item in result.audits] == [
        (1, "INSUFFICIENT"), (2, "SUPPORTED"),
    ]
    assert len(result.repairs) == 1
    assert result.repairs[0].original_text == "The system completed retrieval."
    assert result.repairs[0].repaired_text == "The system uses retrieval."
    assert result.repairs[0].repaired_claim_id == result.page.sections[0].claims[0].id


class InconsistentAudit:
    model = "audit"

    def complete(self, **kwargs):
        claim = kwargs["user"]["claims"][0]
        return {"claims": [{
            "claim_id": claim["claim_id"], "verdict": "SUPPORTED",
            "reason_code": "MISSING_SUPPORT", "reason": "not supported", "source_handles": [],
        }]}


class DropRepair:
    model = "repair"

    def complete(self, **kwargs):
        claim = kwargs["user"]["claims"][0]
        return {"repairs": [{
            "claim_id": claim["claim_id"], "action": "DROP", "text": "",
            "source_handles": [], "reason": "unsupported",
        }]}


def test_inconsistent_supported_verdict_is_intercepted_and_not_publishable() -> None:
    document, source_id, source, page = _inputs()
    result = WikiQualityGate(InconsistentAudit(), DropRepair()).verify(
        page, {source_id: source}, [document],
    )
    assert result.page.status == RevisionStatus.FAILED
    assert any(issue.code == "INCONSISTENT_AUDIT_RESULT" for issue in result.issues)
    assert result.repairs[0].action == "DROP"


def test_repair_limit_drops_only_unsupported_claims() -> None:
    document, source_id, source, page = _inputs()
    page.sections[0].claims.append(WikiClaim(
        id="claim-2", text="The system uses retrieval.", source_ids=[source_id],
    ))

    class AuditEachClaim:
        model = "audit"

        def complete(self, **kwargs):
            return {"claims": [{
                "claim_id": claim["claim_id"],
                "verdict": "INSUFFICIENT" if "completed" in claim["text"] else "SUPPORTED",
                "reason_code": "OVERSTATED" if "completed" in claim["text"] else "ENTAILED",
                "reason": "checked",
                "source_handles": [claim["sources"][0]["source_handle"]],
            } for claim in kwargs["user"]["claims"]]}

    result = WikiQualityGate(AuditEachClaim(), DropRepair(), max_repair_rounds=0).verify(
        page, {source_id: source}, [document],
    )
    assert result.page.status == RevisionStatus.REVIEWING
    assert [claim.id for section in result.page.sections for claim in section.claims] == ["claim-2"]
    assert [issue.target_id for issue in result.issues if issue.code == "UNSUPPORTED_CLAIM_DROPPED"] == ["claim-1"]


def test_independent_audit_rejection_cannot_be_overridden_by_primary_support() -> None:
    document, source_id, source, page = _inputs()
    page.sections[0].claims[0].text = "The system uses retrieval."

    class Primary:
        model = "primary"

        def complete(self, **kwargs):
            claim = kwargs["user"]["claims"][0]
            return {"claims": [{
                "claim_id": claim["claim_id"], "verdict": "SUPPORTED",
                "reason_code": "ENTAILED", "reason": "looks plausible",
                "source_handles": [claim["sources"][0]["source_handle"]],
            }]}

    class Independent:
        model = "independent"

        def complete(self, **kwargs):
            claim = kwargs["user"]["claims"][0]
            return {"claims": [{
                "claim_id": claim["claim_id"], "verdict": "INSUFFICIENT",
                "reason_code": "MISSING_SUPPORT", "reason": "source does not establish the subject",
                "source_handles": [claim["sources"][0]["source_handle"]],
            }]}

    result = WikiQualityGate(
        Primary(), DropRepair(), confirmation_client=Independent(),
    ).verify(page, {source_id: source}, [document])
    assert result.page.status == RevisionStatus.FAILED
    assert result.audits[0].verdict.value == "INSUFFICIENT"
    assert any(issue.code == "CLAIM_AUDIT_DISAGREEMENT" for issue in result.issues)


def test_page_coherence_rejection_blocks_otherwise_supported_page() -> None:
    document, source_id, source, page = _inputs()
    page.sections[0].claims[0].text = "The system uses retrieval."

    class PageReviewer:
        model = "page-reviewer"

        def complete(self, **kwargs):
            assert kwargs["schema_name"] == "wiki_page_coherence"
            return {"accept": False, "reason": "page combines unrelated subjects"}

    result = WikiQualityGate(
        AuditFake(), DropRepair(), page_client=PageReviewer(),
    ).verify(page, {source_id: source}, [document])
    assert result.page.status == RevisionStatus.FAILED
    assert any(issue.code == "PAGE_COHERENCE_REJECTED" for issue in result.issues)


def test_audit_source_outside_claim_is_rejected_without_aborting_batch() -> None:
    document, source_id, source, page = _inputs()
    page.sections[0].claims[0].text = "The system uses retrieval."

    class UnknownHandleAudit:
        model = "unknown-source"

        def complete(self, **kwargs):
            claim = kwargs["user"]["claims"][0]
            return {"claims": [{
                "claim_id": claim["claim_id"], "verdict": "SUPPORTED",
                "reason_code": "ENTAILED", "reason": "wrong source",
                "source_handles": ["s_outside_current_request"],
            }]}

    result = WikiQualityGate(
        AuditFake(), DropRepair(), max_repair_rounds=0,
        confirmation_client=UnknownHandleAudit(),
    ).verify(page, {source_id: source}, [document])
    assert result.page.status == RevisionStatus.FAILED
    assert result.audits[0].verdict.value == "INSUFFICIENT"
    assert any(issue.code == "INVALID_AUDIT_BINDING" for issue in result.issues)


def test_long_non_chinese_narrative_claim_is_dropped_from_chinese_wiki() -> None:
    document, source_id, source, page = _inputs()
    page.title = "系统概述"
    page.sections[0].claims[0].text = "The system uses retrieval."
    result = WikiQualityGate(AuditFake(), DropRepair()).verify(
        page, {source_id: source}, [document],
    )
    assert result.page.status == RevisionStatus.FAILED
    assert result.page.sections == []
    assert any(issue.code == "NON_CHINESE_CLAIM_DROPPED" for issue in result.issues)


def test_unbound_latin_term_in_chinese_claim_is_dropped() -> None:
    document, source_id, source, page = _inputs()
    page.title = "系统概述"
    page.sections[0].claims[0].text = "OtherWiki使用了检索方法。"

    class AlwaysSupport:
        model = "support"

        def complete(self, **kwargs):
            claim = kwargs["user"]["claims"][0]
            return {"claims": [{
                "claim_id": claim["claim_id"], "verdict": "SUPPORTED",
                "reason_code": "ENTAILED", "reason": "claimed supported",
                "source_handles": [claim["sources"][0]["source_handle"]],
            }]}

    result = WikiQualityGate(AlwaysSupport(), DropRepair()).verify(
        page, {source_id: source}, [document],
    )
    assert result.page.status == RevisionStatus.FAILED
    assert any(issue.code == "UNGROUNDED_CLAIM_TERM_DROPPED" for issue in result.issues)


def test_claim_audit_batches_large_page_without_losing_audit_coverage() -> None:
    document, source_id, source, page = _inputs()
    page.sections[0].claims = [
        WikiClaim(id=f"claim-{index}", text="The system uses retrieval.",
                  source_ids=[source_id])
        for index in range(9)
    ]

    class BatchedAudit:
        model = "batched"

        def __init__(self):
            self.sizes = []

        def complete(self, **kwargs):
            claims = kwargs["user"]["claims"]
            self.sizes.append(len(claims))
            return {"claims": [{
                "claim_id": claim["claim_id"], "verdict": "SUPPORTED",
                "reason_code": "ENTAILED", "reason": "direct",
                "source_handles": [claim["sources"][0]["source_handle"]],
            } for claim in claims]}

    audit = BatchedAudit()
    result = WikiQualityGate(audit, DropRepair()).verify(
        page, {source_id: source}, [document],
    )
    assert audit.sizes == [8, 1]
    assert result.page.status == RevisionStatus.REVIEWING
    assert {item.claim_id for item in result.audits} == {
        f"claim-{index}" for index in range(9)
    }
