"""Semantic Claim verification contracts and a bounded deterministic baseline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Protocol

from agent.schemas.research import (
    ClaimDraft,
    ClaimVerificationStatus,
    VerificationResult,
    VerifiedClaim,
    VerifiedEvidence,
)


class SemanticVerifier(Protocol):
    def verify(
        self,
        claim: ClaimDraft,
        evidence: Iterable[VerifiedEvidence],
    ) -> VerificationResult:
        """Judge whether the supplied original excerpts support a Claim."""


class DeterministicSemanticVerifier:
    """Small lexical/numeric baseline for the first vertical slice.

    This is not presented as a fact checker.  It only decides whether the
    Claim wording is supported by the provided excerpts closely enough for the
    demo.  A model-backed verifier can replace this Protocol later.
    """

    def verify(
        self,
        claim: ClaimDraft,
        evidence: Iterable[VerifiedEvidence],
    ) -> VerificationResult:
        evidence_list = list(evidence)
        by_id = {item.evidence_id: item for item in evidence_list}
        selected: list[VerifiedEvidence] = []
        missing_ids: list[str] = []
        for evidence_id in claim.evidence_ids:
            item = by_id.get(evidence_id)
            if item is None:
                missing_ids.append(evidence_id)
            elif item.research_id != claim.research_id:
                missing_ids.append(evidence_id)
            else:
                selected.append(item)

        if missing_ids:
            return VerificationResult(
                claim_id=claim.claim_id,
                status=ClaimVerificationStatus.UNSUPPORTED,
                evidence_ids=list(claim.evidence_ids),
                reason=f"missing_or_foreign_evidence:{','.join(missing_ids)}",
            )
        if not selected:
            return VerificationResult(
                claim_id=claim.claim_id,
                status=ClaimVerificationStatus.UNSUPPORTED,
                evidence_ids=[],
                reason="claim_has_no_evidence",
            )

        claim_numbers = self._numbers(claim.claim_text)
        evidence_number_sets = [self._numbers(item.excerpt) for item in selected]
        evidence_numbers = {
            number for numbers in evidence_number_sets for number in numbers
        }
        # If multiple original excerpts disagree on the numeric payload of a
        # numeric Claim, preserve the conflict before checking whether one
        # excerpt happens to contain the claimed value.
        if (
            claim_numbers
            and len(selected) > 1
            and any(claim_numbers & numbers for numbers in evidence_number_sets)
            and len({tuple(sorted(numbers)) for numbers in evidence_number_sets}) > 1
        ):
            return VerificationResult(
                claim_id=claim.claim_id,
                status=ClaimVerificationStatus.CONFLICTING,
                evidence_ids=[item.evidence_id for item in selected],
                reason="evidence_contains_conflicting_numeric_values",
            )
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            return VerificationResult(
                claim_id=claim.claim_id,
                status=ClaimVerificationStatus.UNSUPPORTED,
                evidence_ids=[item.evidence_id for item in selected],
                reason="claim_numeric_detail_not_fully_present_in_evidence",
            )

        combined = " ".join(item.excerpt for item in selected)
        overlap = self._overlap_ratio(claim.claim_text, combined)
        if claim.claim_text.casefold().strip() in combined.casefold():
            status = ClaimVerificationStatus.SUPPORTED
            reason = "claim_text_found_in_original_evidence"
        elif overlap >= 0.55:
            status = ClaimVerificationStatus.SUPPORTED
            reason = "claim_tokens_supported_by_original_evidence"
        elif overlap >= 0.25:
            status = ClaimVerificationStatus.PARTIAL
            reason = "claim_has_partial_lexical_support"
        else:
            status = ClaimVerificationStatus.UNSUPPORTED
            reason = "claim_has_insufficient_lexical_support"
        return VerificationResult(
            claim_id=claim.claim_id,
            status=status,
            evidence_ids=[item.evidence_id for item in selected],
            reason=reason,
        )

    def verify_many(
        self,
        claims: Iterable[ClaimDraft],
        evidence: Iterable[VerifiedEvidence],
    ) -> list[VerifiedClaim]:
        evidence_list = list(evidence)
        verified: list[VerifiedClaim] = []
        for claim in claims:
            result = self.verify(claim, evidence_list)
            verified.append(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    research_id=claim.research_id,
                    claim_text=claim.claim_text,
                    status=result.status,
                    evidence_ids=result.evidence_ids,
                    criterion_ids=claim.criterion_ids,
                    reason=result.reason,
                )
            )
        return verified

    @staticmethod
    def _numbers(text: str) -> set[str]:
        return set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?", text))

    @classmethod
    def _overlap_ratio(cls, claim: str, evidence: str) -> float:
        claim_tokens = cls._tokens(claim)
        if not claim_tokens:
            return 0.0
        evidence_tokens = cls._tokens(evidence)
        return len(claim_tokens & evidence_tokens) / len(claim_tokens)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(
            re.findall(
                r"[A-Za-z][A-Za-z0-9_-]*|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]",
                text.casefold(),
            )
        )


class MockSemanticVerifier:
    """Fixture-driven verifier for hermetic Full Vertical Slice tests."""

    def __init__(
        self,
        statuses: Mapping[str, ClaimVerificationStatus | str],
    ) -> None:
        self.statuses = {
            claim_id: ClaimVerificationStatus(status)
            for claim_id, status in statuses.items()
        }

    def verify(
        self,
        claim: ClaimDraft,
        evidence: Iterable[VerifiedEvidence],
    ) -> VerificationResult:
        selected_ids = [item.evidence_id for item in evidence]
        status = self.statuses.get(
            claim.claim_id,
            ClaimVerificationStatus.SUPPORTED if selected_ids else ClaimVerificationStatus.UNSUPPORTED,
        )
        return VerificationResult(
            claim_id=claim.claim_id,
            status=status,
            evidence_ids=list(claim.evidence_ids),
            reason="fixture_semantic_verdict",
        )


__all__ = [
    "DeterministicSemanticVerifier",
    "MockSemanticVerifier",
    "SemanticVerifier",
]
