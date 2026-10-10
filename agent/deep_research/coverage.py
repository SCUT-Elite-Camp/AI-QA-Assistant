"""Deterministic Acceptance Criterion coverage for the Core Vertical Slice."""

from __future__ import annotations

from collections.abc import Iterable

from agent.schemas.research import (
    AcceptanceCriterion,
    CriterionCoverage,
    CoverageResult,
    Finding,
)


class CoverageEngine:
    """Aggregate Finding→Criterion mappings without a multidimensional matrix."""

    def compute(
        self,
        research_id: str,
        criteria: Iterable[AcceptanceCriterion],
        findings: Iterable[Finding],
    ) -> CoverageResult:
        criteria_list = list(criteria)
        findings_list = [
            finding for finding in findings if finding.research_id == research_id
        ]
        covered_evidence: dict[str, set[str]] = {
            criterion.criterion_id: set() for criterion in criteria_list
        }
        for finding in findings_list:
            for criterion_id in finding.covers:
                if criterion_id in covered_evidence and finding.evidence_ids:
                    covered_evidence[criterion_id].update(finding.evidence_ids)

        covered: list[str] = []
        missing: list[str] = []
        criterion_results: list[CriterionCoverage] = []
        for criterion in criteria_list:
            evidence_ids = sorted(covered_evidence[criterion.criterion_id])
            is_covered = bool(evidence_ids)
            criterion_results.append(
                CriterionCoverage(
                    criterion_id=criterion.criterion_id,
                    covered=is_covered,
                    evidence_ids=evidence_ids,
                )
            )
            if is_covered:
                covered.append(criterion.criterion_id)
            elif criterion.required:
                missing.append(criterion.criterion_id)

        return CoverageResult(
            research_id=research_id,
            covered=covered,
            missing=missing,
            sufficient=not missing,
            criteria=criterion_results,
        )


def compute_coverage(
    research_id: str,
    criteria: Iterable[AcceptanceCriterion],
    findings: Iterable[Finding],
) -> CoverageResult:
    """Functional convenience wrapper for Graph node integration."""

    return CoverageEngine().compute(research_id, criteria, findings)


__all__ = ["CoverageEngine", "compute_coverage"]
