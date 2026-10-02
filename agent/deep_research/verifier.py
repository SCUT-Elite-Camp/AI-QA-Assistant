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
            len(selected) > 1
            and self._claim_expects_one_value(claim.claim_text)
            and all(evidence_number_sets)
            and self._same_subject(selected)
            and self._same_fact_scope(selected)
            and self._has_conflicting_claim_values(claim_numbers, evidence_number_sets)
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

    @staticmethod
    def _claim_expects_one_value(text: str) -> bool:
        """Only classify disagreement for a single-value factual assertion.

        Comparative and change-over-time claims intentionally contain several
        different values.  Treating those values as disagreement caused normal
        W30/W34 comparisons to be surfaced as source conflicts.
        """

        lowered = text.casefold()
        comparison_markers = (
            "compare", "versus", " vs ", "change", "increase", "decrease",
            "difference", "trend", "分别", "对比", "比较", "变化", "增加",
            "减少", "从", "到", "各", "不同",
        )
        return not any(marker in lowered for marker in comparison_markers)

    @staticmethod
    def _has_conflicting_claim_values(
        claim_numbers: set[str], evidence_number_sets: list[set[str]]
    ) -> bool:
        """Compare source-specific values after removing shared dates/versions."""

        shared = set.intersection(*(set(values) for values in evidence_number_sets))
        relevant = [numbers - shared for numbers in evidence_number_sets]
        non_empty = [values for values in relevant if values]
        return len(non_empty) > 1 and len({tuple(sorted(values)) for values in non_empty}) > 1

    @classmethod
    def _same_subject(cls, evidence: list[VerifiedEvidence]) -> bool:
        token_sets = [cls._tokens(item.excerpt) for item in evidence]
        for index, left in enumerate(token_sets):
            for right in token_sets[index + 1:]:
                smaller = min(len(left), len(right))
                if smaller >= 4 and len(left & right) / smaller >= 0.35:
                    return True
        return False

    @classmethod
    def _same_fact_scope(cls, evidence: list[VerifiedEvidence]) -> bool:
        """Different explicit periods are comparison inputs, not contradictions."""

        scopes = [cls._scope_markers(item.excerpt) for item in evidence]
        explicit = [scope for scope in scopes if scope]
        if len(explicit) < 2:
            return True
        common = set.intersection(*(set(scope) for scope in explicit))
        return bool(common)

    @staticmethod
    def _scope_markers(text: str) -> set[str]:
        markers = {
            item.upper()
            for item in re.findall(r"\bW\d{1,2}\b|\b\d{4}-W\d{1,2}\b", text, re.IGNORECASE)
        }
        if markers:
            return markers
        # A year is a useful scope only when no more precise sprint/week marker
        # is present. Shared years still permit conflict detection.
        return set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text))

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
        # Ignore numeric prefixes embedded in document IDs, hashes and other
        # alphanumeric identifiers. Treating ``54892...abc`` as the factual
        # number ``54892`` rejects otherwise supported multi-source claims.
        return set(
            re.findall(
                r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?(?![A-Za-z0-9])",
                text,
            )
        )

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
