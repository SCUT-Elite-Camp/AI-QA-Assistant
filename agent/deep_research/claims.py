"""Claim-first generation from persisted Findings."""

from __future__ import annotations

from collections.abc import Iterable

from agent.schemas.research import ClaimDraft, Finding


class ClaimGenerator:
    """Convert Findings to bounded ClaimDraft objects without new facts."""

    def generate(
        self,
        findings: Iterable[Finding],
        *,
        research_id: str | None = None,
    ) -> list[ClaimDraft]:
        selected = [
            finding
            for finding in findings
            if research_id is None or finding.research_id == research_id
        ]
        claims: list[ClaimDraft] = []
        # Two identical sentences backed by different evidence can represent
        # a conflict.  Deduplicate only an identical statement/evidence pair.
        seen_facts: set[tuple[str, tuple[str, ...]]] = set()
        used_ids: set[str] = set()
        for finding in selected:
            statement = finding.statement.strip()
            fact_key = (statement, tuple(finding.evidence_ids))
            if not statement or fact_key in seen_facts:
                continue
            seen_facts.add(fact_key)
            base_id = f"claim-{finding.finding_id}"
            claim_id = base_id
            suffix = 2
            while claim_id in used_ids:
                claim_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(claim_id)
            claims.append(
                ClaimDraft(
                    claim_id=claim_id,
                    research_id=finding.research_id,
                    claim_text=statement,
                    evidence_ids=list(finding.evidence_ids),
                    criterion_ids=list(finding.covers),
                )
            )
        return claims


def generate_claims(
    findings: Iterable[Finding],
    *,
    research_id: str | None = None,
) -> list[ClaimDraft]:
    return ClaimGenerator().generate(findings, research_id=research_id)


__all__ = ["ClaimGenerator", "generate_claims"]
