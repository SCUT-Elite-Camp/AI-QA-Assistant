"""Strict domain models shared by the generic Wiki build pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CandidateKind(StrEnum):
    ENTITY = "ENTITY"
    CONCEPT = "CONCEPT"


class EntityCategory(StrEnum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    PRODUCT = "PRODUCT"
    SYSTEM = "SYSTEM"
    COMPONENT = "COMPONENT"
    TECHNOLOGY = "TECHNOLOGY"
    LOCATION = "LOCATION"
    OTHER = "OTHER"


class CandidateStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    EVIDENCE_BOUND = "EVIDENCE_BOUND"
    REJECTED = "REJECTED"


class PromotionStatus(StrEnum):
    PENDING = "PENDING"
    PROMOTED = "PROMOTED"
    SKIPPED = "SKIPPED"


class WikiPageType(StrEnum):
    SUMMARY = "SUMMARY"
    ENTITY = "ENTITY"
    CONCEPT = "CONCEPT"
    INDEX = "INDEX"
    SYNTHESIS = "SYNTHESIS"
    COMPARISON = "COMPARISON"


class RevisionStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWING = "REVIEWING"
    PUBLISHED = "PUBLISHED"
    STALE = "STALE"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class VerificationVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    CONTRADICTED = "CONTRADICTED"


class VerificationReason(StrEnum):
    ENTAILED = "ENTAILED"
    MISSING_SUPPORT = "MISSING_SUPPORT"
    OVERSTATED = "OVERSTATED"
    WRONG_SUBJECT = "WRONG_SUBJECT"
    WRONG_RELATION = "WRONG_RELATION"
    WRONG_TIME_OR_STATUS = "WRONG_TIME_OR_STATUS"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INVALID_SOURCE = "INVALID_SOURCE"


class WikiScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_scope: Literal["enterprise", "personal"]
    knowledge_base_id: str = Field(min_length=1)
    owner_id: str = ""

    @model_validator(mode="after")
    def validate_owner(self) -> "WikiScope":
        if self.source_scope == "personal" and not self.owner_id.strip():
            raise ValueError("personal Wiki scope requires owner_id")
        if self.source_scope == "enterprise" and self.owner_id:
            object.__setattr__(self, "owner_id", "")
        return self


class WikiSourceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    section_id: str = ""
    heading_path: tuple[str, ...] = ()
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = ""
    ordinal: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_hash(self) -> "WikiSourceChunk":
        actual = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if actual != self.text_sha256:
            raise ValueError("Wiki source chunk hash does not match text")
        return self


class WikiKnowledgeSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    evidence_start: int = Field(ge=0)
    evidence_end: int = Field(gt=0)
    knowledge_start: int = Field(ge=0)
    knowledge_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "WikiKnowledgeSpan":
        if self.evidence_end <= self.evidence_start or self.knowledge_end <= self.knowledge_start:
            raise ValueError("Wiki knowledge span range is invalid")
        return self


class WikiKnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    section_id: str = ""
    heading_path: tuple[str, ...] = ()
    content_type: str = "prose"
    text: str = Field(min_length=1)
    source_spans: tuple[WikiKnowledgeSpan, ...] = Field(min_length=1)
    ordinal: int = Field(ge=0)


class WikiSourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: WikiScope
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = ""
    doc_type: str = ""
    active_version: bool = True
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunks: tuple[WikiSourceChunk, ...] = Field(min_length=1)
    knowledge_chunks: tuple[WikiKnowledgeChunk, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chunks(self) -> "WikiSourceDocument":
        ids = [chunk.evidence_id for chunk in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("Wiki source Evidence IDs must be unique within a document")
        knowledge_ids = [chunk.id for chunk in self.knowledge_chunks]
        if len(knowledge_ids) != len(set(knowledge_ids)):
            raise ValueError("Wiki knowledge chunk IDs must be unique within a document")
        evidence = {chunk.evidence_id: chunk for chunk in self.chunks}
        for knowledge in self.knowledge_chunks:
            for span in knowledge.source_spans:
                source = evidence.get(span.evidence_id)
                if source is None:
                    raise ValueError("Wiki knowledge chunk references unknown Evidence")
                if span.evidence_end > len(source.text) or span.knowledge_end > len(knowledge.text):
                    raise ValueError("Wiki knowledge span exceeds source boundaries")
                if source.text[span.evidence_start:span.evidence_end] != knowledge.text[
                    span.knowledge_start:span.knowledge_end
                ]:
                    raise ValueError("Wiki knowledge chunk is not an exact Evidence derivative")
        if not self.active_version:
            raise ValueError("Wiki builds accept active document versions only")
        return self


class CandidateSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    section_id: str = ""
    support_quote: str = Field(min_length=1)
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_range(self) -> "CandidateSource":
        if self.quote_end <= self.quote_start:
            raise ValueError("support quote range is invalid")
        return self


class WikiCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    scope: WikiScope
    kind: CandidateKind
    name: str = Field(min_length=2)
    category: EntityCategory | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    document_ids: list[str] = Field(min_length=1)
    sources: list[CandidateSource] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.EXTRACTED
    promotion_status: PromotionStatus = PromotionStatus.PENDING
    promotion_reason: str = ""
    generator_model: str = ""
    prompt_version: str = ""
    input_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_kind_and_sources(self) -> "WikiCandidate":
        if self.kind == CandidateKind.CONCEPT and self.category is not None:
            raise ValueError("concept candidates do not carry entity categories")
        if self.status == CandidateStatus.EVIDENCE_BOUND and not self.sources:
            raise ValueError("evidence-bound candidates require at least one source")
        if self.sources and self.status == CandidateStatus.EXTRACTED:
            self.status = CandidateStatus.EVIDENCE_BOUND
        if self.status != CandidateStatus.EVIDENCE_BOUND and self.promotion_status == PromotionStatus.PROMOTED:
            raise ValueError("only Evidence-bound candidates may be promoted")
        return self


class WikiIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    scope: WikiScope
    kind: CandidateKind
    canonical_name: str = Field(min_length=2)
    slug: str = Field(min_length=3)
    category: EntityCategory | None = None
    aliases: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    description: str = ""

    @model_validator(mode="after")
    def validate_kind(self) -> "WikiIdentity":
        if self.kind == CandidateKind.CONCEPT and self.category is not None:
            raise ValueError("concept identities do not carry entity categories")
        return self


class WikiFolder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    scope: WikiScope
    title: str = Field(min_length=1)
    parent_id: str | None = None
    depth: int = Field(ge=0, le=2)
    manual: bool = False


class WikiPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_id: str
    folder_id: str
    manual: bool = False


class WikiClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str = Field(min_length=3)
    rendered_text: str = ""
    source_ids: list[str] = Field(min_length=1)
    verdict: VerificationVerdict | None = None
    reason_code: VerificationReason | None = None
    reason: str = ""

    @model_validator(mode="after")
    def validate_verdict_reason(self) -> "WikiClaim":
        if self.verdict is None and self.reason_code is not None:
            raise ValueError("unverified claim cannot have a reason code")
        if self.verdict == VerificationVerdict.SUPPORTED and self.reason_code != VerificationReason.ENTAILED:
            raise ValueError("SUPPORTED requires ENTAILED reason code")
        if self.verdict in {VerificationVerdict.INSUFFICIENT, VerificationVerdict.CONTRADICTED}:
            if self.reason_code in {None, VerificationReason.ENTAILED}:
                raise ValueError("unsupported verdict requires a non-entailed reason code")
        return self


class WikiSectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    claims: list[WikiClaim] = Field(default_factory=list)


class WikiPageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    scope: WikiScope
    page_type: WikiPageType
    slug: str
    title: str = Field(min_length=1)
    summary: str = ""
    folder_id: str | None = None
    identity_id: str | None = None
    document_version_ids: list[str] = Field(default_factory=list)
    sections: list[WikiSectionDraft] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    status: RevisionStatus = RevisionStatus.DRAFT
    generator_model: str = ""
    prompt_version: str = ""
    input_hash: str

    @model_validator(mode="after")
    def validate_page_target(self) -> "WikiPageDraft":
        if self.page_type in {WikiPageType.ENTITY, WikiPageType.CONCEPT} and not self.identity_id:
            raise ValueError("entity and concept pages require identity_id")
        if self.page_type in {WikiPageType.SYNTHESIS, WikiPageType.COMPARISON}:
            raise ValueError("synthesis and comparison pages require an explicit agent or human workflow")
        return self


class WikiIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    target_kind: str
    target_id: str


class WikiClaimAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_id: str = Field(min_length=1)
    audit_round: int = Field(ge=1)
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=3)
    source_ids: tuple[str, ...] = Field(min_length=1)
    verdict: VerificationVerdict
    reason_code: VerificationReason
    reason: str = ""


class WikiClaimRepairRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_id: str = Field(min_length=1)
    repair_round: int = Field(ge=1, le=2)
    original_claim_id: str = Field(min_length=1)
    original_text: str = Field(min_length=3)
    action: Literal["REWRITE", "DROP"]
    repaired_claim_id: str = ""
    repaired_text: str = ""
    source_ids: tuple[str, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def validate_action(self) -> "WikiClaimRepairRecord":
        if self.action == "REWRITE" and (
            not self.repaired_claim_id or len(self.repaired_text) < 3 or not self.source_ids
        ):
            raise ValueError("Wiki claim rewrite record requires a repaired claim and sources")
        if self.action == "DROP" and (
            self.repaired_claim_id or self.repaired_text or self.source_ids
        ):
            raise ValueError("Wiki claim drop record cannot retain repaired content")
        return self


class WikiBuildDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_version_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WikiBuildArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: WikiScope
    revision: str
    input_hash: str
    generator_model: str
    prompt_version: str
    documents: list[WikiBuildDocument]
    candidates: list[WikiCandidate]
    identities: list[WikiIdentity]
    folders: list[WikiFolder]
    pages: list[WikiPageDraft]
    claim_audits: list[WikiClaimAuditRecord] = Field(default_factory=list)
    claim_repairs: list[WikiClaimRepairRecord] = Field(default_factory=list)
    issues: list[WikiIssue] = Field(default_factory=list)


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized).split())


def stable_id(prefix: str, *parts: str) -> str:
    normalized = "\n".join(str(part).strip() for part in parts)
    if not prefix or not normalized.strip():
        raise ValueError("stable ID requires a prefix and identity material")
    return f"{prefix}_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]}"


def stable_slug(name: str, identity_id: str) -> str:
    base = normalize_name(name).replace("_", "-").replace(" ", "-")
    base = re.sub(r"-+", "-", base).strip("-") or "topic"
    return f"{base[:72]}-{identity_id[-8:]}"


def source_reference_id(source: CandidateSource) -> str:
    return stable_id(
        "ws",
        source.document_version_id,
        source.evidence_id,
        str(source.quote_start),
        str(source.quote_end),
    )
