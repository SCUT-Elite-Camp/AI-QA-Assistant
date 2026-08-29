"""Deterministic Claim/Evidence trust gate."""

from __future__ import annotations

from dataclasses import dataclass

from agent.schemas.research import ClaimDraft, ClaimVerificationStatus, SourceManifest, VerificationResult
from .repository import ResearchNotFoundError, SQLiteResearchRepository


@dataclass(frozen=True)
class StructuralResult:
    claim_id: str
    valid: bool
    error_codes: tuple[str, ...]
    verification: VerificationResult


class StructuralVerifier:
    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository

    def verify(self, claim: ClaimDraft, manifest: SourceManifest) -> StructuralResult:
        errors: list[str] = []
        if claim.research_id != manifest.research_id:
            errors.append("claim_job_mismatch")
        allowed = {document.doc_id: document for document in manifest.documents}
        if not claim.evidence_ids:
            errors.append("claim_without_evidence")
        for evidence_id in claim.evidence_ids:
            try:
                item = self.repository.get_evidence(evidence_id)
            except ResearchNotFoundError:
                errors.append(f"missing_evidence:{evidence_id}")
                continue
            if item.research_id != claim.research_id:
                errors.append(f"cross_job_evidence:{evidence_id}")
            if item.doc_id not in allowed:
                errors.append(f"evidence_outside_manifest:{evidence_id}")
            elif item.content_hash != allowed[item.doc_id].content_hash:
                errors.append(f"evidence_version_mismatch:{evidence_id}")
            if not item.locator:
                errors.append(f"missing_locator:{evidence_id}")
            if not item.content_hash:
                errors.append(f"missing_content_hash:{evidence_id}")
        verification = VerificationResult(
            claim_id=claim.claim_id,
            status=ClaimVerificationStatus.UNSUPPORTED if errors else ClaimVerificationStatus.SUPPORTED,
            evidence_ids=claim.evidence_ids,
            reason=";".join(errors) if errors else "structural_checks_passed",
        )
        self.repository.save_verification(verification, phase="structural")
        return StructuralResult(claim.claim_id, not errors, tuple(errors), verification)


__all__ = ["StructuralResult", "StructuralVerifier"]
