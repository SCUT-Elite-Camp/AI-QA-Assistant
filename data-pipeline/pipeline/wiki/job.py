"""Offline orchestration for incremental Wiki builds and atomic publication."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from .domain import (
    CandidateStatus,
    PromotionStatus,
    RevisionStatus,
    VerificationVerdict,
    WikiBuildArtifact,
    WikiBuildDocument,
    WikiCandidate,
    WikiClaimAuditRecord,
    WikiClaimRepairRecord,
    WikiFolder,
    WikiIdentity,
    WikiIssue,
    WikiPageDraft,
    WikiPlacement,
    WikiScope,
    WikiSourceDocument,
    source_reference_id,
)
from .extraction import (
    BINDING_PROMPT_VERSION,
    CANDIDATE_PROMPT_VERSION,
    PROMOTION_PROMPT_VERSION,
    CandidateExtractor,
    CandidatePromotionSelector,
)
from .finalize import finalize_wiki_pages
from .identity import IDENTITY_PROMPT_VERSION, IdentityResolver
from .page import PAGE_PROMPT_VERSION, WikiPageCompiler
from .quality import (
    AUDIT_PROMPT_VERSION, PAGE_AUDIT_PROMPT_VERSION, REPAIR_PROMPT_VERSION,
    WikiQualityGate, build_source_catalog,
)
from .taxonomy import TAXONOMY_PROMPT_VERSION, TaxonomyPlanner


ONTOLOGY_VERSION = "wiki-ontology-v1"
FINALIZE_VERSION = "wiki-finalize-v2"


class WikiRepository(Protocol):
    def reusable_revision(self, **kwargs: Any) -> str | None: ...
    def load_published_candidates(self, document_version_id: str, **kwargs: Any) -> list[dict[str, Any]] | None: ...
    def load_published_identities(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def load_published_taxonomy(self, **kwargs: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...
    def load_published_page_cache(self, **kwargs: Any) -> dict[str, dict[str, Any]]: ...
    def load_published_page_audit_cache(self, **kwargs: Any) -> dict[str, dict[str, list[dict[str, Any]]]]: ...
    def save_artifact(self, artifact: Any, source_catalog: dict[str, Any]) -> None: ...
    def publish_revision(self, **kwargs: Any) -> None: ...


class WikiBuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    publish: bool = False


class WikiBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: str
    input_hash: str
    reused: bool
    published: bool
    documents: int
    candidates: int
    identities: int
    pages: int
    failed_pages: int


class WikiBuildService:
    def __init__(
        self,
        *,
        repository: WikiRepository,
        extractor: CandidateExtractor,
        promotion_selector: CandidatePromotionSelector,
        identity_resolver: IdentityResolver,
        taxonomy_planner: TaxonomyPlanner,
        page_compiler: WikiPageCompiler,
        quality_gate: WikiQualityGate,
        config: WikiBuildConfig | None = None,
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.promotion_selector = promotion_selector
        self.identity_resolver = identity_resolver
        self.taxonomy_planner = taxonomy_planner
        self.page_compiler = page_compiler
        self.quality_gate = quality_gate
        self.config = config or WikiBuildConfig()

    def run(
        self,
        documents: list[WikiSourceDocument],
        *,
        revision: str | None = None,
    ) -> WikiBuildResult:
        if not self.config.enabled:
            raise RuntimeError("WIKI_INGEST_ENABLED is false")
        scope = _validate_documents(documents)
        input_hash = _build_input_hash(documents, self)
        context = _context(scope)
        reusable = self.repository.reusable_revision(input_hash=input_hash, **context)
        if reusable:
            return WikiBuildResult(
                revision=reusable, input_hash=input_hash, reused=True, published=True,
                documents=len(documents), candidates=0, identities=0, pages=0, failed_pages=0,
            )
        revision = revision or f"wr_{input_hash[:24]}"
        candidates: list[WikiCandidate] = []
        issues: list[WikiIssue] = []
        for document in documents:
            cached = self.repository.load_published_candidates(
                document.document_version_id, **context,
            )
            if cached is not None:
                cached_values = [WikiCandidate.model_validate(item) for item in cached]
                if any(item.scope != scope for item in cached_values):
                    raise ValueError("cached Wiki candidates cross the current scope")
                candidates.extend(cached_values)
                continue
            extraction = self.extractor.extract(document)
            candidates.extend(extraction.candidates)
            issues.extend(extraction.issues)
        candidates, promotion_issues = self.promotion_selector.select(candidates)
        issues.extend(promotion_issues)
        accepted = [item for item in candidates if item.status == CandidateStatus.EVIDENCE_BOUND]
        promoted = [
            item for item in accepted
            if item.promotion_status == PromotionStatus.PROMOTED
        ]
        existing = [
            WikiIdentity.model_validate(item)
            for item in self.repository.load_published_identities(**context)
        ]
        existing = _prune_identities(existing, promoted)
        identities, identity_issues = self.identity_resolver.resolve_with_issues(
            promoted, existing=existing,
        )
        issues.extend(identity_issues)
        folder_values, placement_values = self.repository.load_published_taxonomy(**context)
        folders = [WikiFolder.model_validate(item) for item in folder_values]
        placements = [WikiPlacement.model_validate(item) for item in placement_values]
        identity_ids = {item.id for item in identities}
        placements = [item for item in placements if item.identity_id in identity_ids]
        folders, placements = self.taxonomy_planner.plan(
            identities, existing_folders=folders, existing_placements=placements,
        )
        raw_page_cache = self.repository.load_published_page_cache(**context)
        raw_audit_cache = self.repository.load_published_page_audit_cache(**context)
        page_cache = {
            key: page for key, value in raw_page_cache.items()
            if _cached_page_matches_audit(
                page := WikiPageDraft.model_validate(value), raw_audit_cache.get(key) or {},
                quality_tag=self.quality_gate.cache_tag,
            )
        }
        pages = self.page_compiler.compile(
            documents, accepted, identities, folders, placements, page_cache=page_cache,
        )
        sources = build_source_catalog(documents, accepted)
        verified_pages: list[WikiPageDraft] = []
        claim_audits = []
        claim_repairs = []
        for page in pages:
            cached_page = page_cache.get(page.input_hash)
            if cached_page is not None and _fully_supported(cached_page):
                value = page.model_copy(deep=True)
                value.status = RevisionStatus.REVIEWING
                verified_pages.append(value)
                cached_trace = raw_audit_cache.get(page.input_hash) or {}
                cached_audits = [
                    WikiClaimAuditRecord.model_validate(item)
                    for item in cached_trace.get("audits") or []
                ]
                claim_audits.extend(cached_audits)
                claim_repairs.extend(
                    WikiClaimRepairRecord.model_validate(item)
                    for item in cached_trace.get("repairs") or []
                )
                continue
            result = self.quality_gate.verify(page, sources, documents)
            verified_pages.append(result.page)
            claim_audits.extend(result.audits)
            claim_repairs.extend(result.repairs)
            issues.extend(result.issues)
        finalized_pages = finalize_wiki_pages(verified_pages, identities)
        artifact = WikiBuildArtifact(
            scope=scope,
            revision=revision,
            input_hash=input_hash,
            generator_model=self.extractor.client.model,
            prompt_version=_combined_prompt_version(),
            documents=[WikiBuildDocument(
                document_id=document.document_id,
                document_version_id=document.document_version_id,
                content_sha256=document.content_sha256,
            ) for document in documents],
            candidates=candidates,
            identities=identities,
            folders=folders,
            pages=finalized_pages,
            claim_audits=claim_audits,
            claim_repairs=claim_repairs,
            issues=issues,
        )
        self.repository.save_artifact(artifact, sources)
        failed_pages = sum(page.status != RevisionStatus.REVIEWING for page in verified_pages)
        published = False
        if self.config.publish and not failed_pages:
            self.repository.publish_revision(revision=revision, **context)
            published = True
        return WikiBuildResult(
            revision=revision,
            input_hash=input_hash,
            reused=False,
            published=published,
            documents=len(documents),
            candidates=len(candidates),
            identities=len(identities),
            pages=len(verified_pages),
            failed_pages=failed_pages,
        )


def _validate_documents(documents: list[WikiSourceDocument]) -> WikiScope:
    if not documents:
        raise ValueError("Wiki build requires at least one source document")
    scope = documents[0].scope
    if any(document.scope != scope for document in documents):
        raise ValueError("Wiki build cannot cross source scopes")
    versions = [document.document_version_id for document in documents]
    if len(versions) != len(set(versions)):
        raise ValueError("Wiki build document versions must be unique")
    return scope


def _build_input_hash(documents: list[WikiSourceDocument], service: WikiBuildService) -> str:
    value = {
        "documents": sorted(
            (document.document_id, document.document_version_id, document.content_sha256)
            for document in documents
        ),
        "ontology": ONTOLOGY_VERSION,
        "prompts": _combined_prompt_version(),
        "extraction": {
            "granularity": service.extractor.granularity,
            "target_language": service.extractor.target_language,
            "max_candidates_per_document": service.extractor.max_candidates_per_document,
        },
        "page_compilation": {
            "target_language": service.page_compiler.target_language,
            "max_source_chars": service.page_compiler.max_source_chars,
        },
        "models": sorted({
            service.extractor.client.model,
            service.promotion_selector.client.model,
            service.identity_resolver.client.model,
            service.taxonomy_planner.client.model,
            service.page_compiler.client.model,
            service.quality_gate.audit_client.model,
            service.quality_gate.repair_client.model,
            service.quality_gate.confirmation_client.model if service.quality_gate.confirmation_client else "",
            service.quality_gate.page_client.model if service.quality_gate.page_client else "",
            service.promotion_selector.confirmation_client.model if service.promotion_selector.confirmation_client else "",
        }),
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _combined_prompt_version() -> str:
    return "+".join([
        CANDIDATE_PROMPT_VERSION,
        BINDING_PROMPT_VERSION,
        PROMOTION_PROMPT_VERSION,
        IDENTITY_PROMPT_VERSION,
        TAXONOMY_PROMPT_VERSION,
        PAGE_PROMPT_VERSION,
        AUDIT_PROMPT_VERSION,
        PAGE_AUDIT_PROMPT_VERSION,
        REPAIR_PROMPT_VERSION,
        ONTOLOGY_VERSION,
        FINALIZE_VERSION,
    ])


def _prune_identities(
    identities: list[WikiIdentity], candidates: list[WikiCandidate],
) -> list[WikiIdentity]:
    candidate_by_id = {item.id: item for item in candidates}
    result: list[WikiIdentity] = []
    for identity in identities:
        retained = [candidate_by_id[item] for item in identity.candidate_ids if item in candidate_by_id]
        if not retained:
            continue
        identity.candidate_ids = sorted(item.id for item in retained)
        identity.source_ids = sorted({
            source_reference_id(source) for item in retained for source in item.sources
        })
        supported_names = {value for item in retained for value in [item.name, *item.aliases]}
        if identity.canonical_name not in supported_names:
            identity.canonical_name = min(supported_names, key=lambda value: (len(value), value.casefold()))
        identity.aliases = sorted(supported_names - {identity.canonical_name})
        result.append(identity)
    return result


def _fully_supported(page: WikiPageDraft) -> bool:
    claims = [claim for section in page.sections for claim in section.claims]
    return (
        page.page_type.value == "INDEX"
        or bool(claims) and all(claim.verdict == VerificationVerdict.SUPPORTED for claim in claims)
    )


def _cached_page_matches_audit(
    page: WikiPageDraft, trace: dict[str, Any], *, quality_tag: str | None = None,
) -> bool:
    if quality_tag is not None and not page.prompt_version.endswith("+" + quality_tag):
        return False
    claims = {
        (claim.id, claim.text, tuple(sorted(claim.source_ids)))
        for section in page.sections for claim in section.claims
    }
    if not claims:
        return False
    supported = {
        (audit.claim_id, audit.claim_text, tuple(sorted(audit.source_ids)))
        for value in trace.get("audits") or []
        if (audit := WikiClaimAuditRecord.model_validate(value)).verdict == VerificationVerdict.SUPPORTED
    }
    return claims <= supported


def _context(scope: WikiScope) -> dict[str, str]:
    return {
        "source_scope": scope.source_scope,
        "owner_id": scope.owner_id,
        "knowledge_base_id": scope.knowledge_base_id,
    }
