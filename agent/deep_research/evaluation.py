"""Deterministic quality gates for comparing Research runtime variants."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.research import ClaimVerificationStatus, ResearchResultStatus

from .progress import ResearchProgressService
from .repository import SQLiteResearchRepository


class ResearchQualityBaseline(BaseModel):
    """A stable, JSON-serializable snapshot for one completed Research Job."""

    model_config = ConfigDict(extra="forbid")

    research_id: str
    result_status: ResearchResultStatus
    source_scope_violations: int = Field(ge=0)
    citation_coverage: float = Field(ge=0, le=1)
    broken_citations: int = Field(ge=0)
    unsupported_claims_in_report: int = Field(ge=0)
    duplicate_evidence_ids: int = Field(ge=0)
    duplicate_event_keys: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    limitation_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    recovery_count: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    passed: bool


def evaluate_research_run(
    repository: SQLiteResearchRepository,
    research_id: str,
) -> ResearchQualityBaseline:
    """Evaluate scope, citation integrity and unsupported-claim leakage."""

    job = repository.get_job(research_id)
    if job.result_status is None:
        raise ValueError("research_run_has_no_result")
    manifest = repository.get_manifest(research_id)
    report = repository.get_report(research_id)
    evidence = repository.list_evidence(research_id)
    events = repository.list_events(research_id, limit=100)
    claims = {item.claim_id: item for item in repository.list_claims(research_id)}
    verifications = repository.list_verifications(research_id)

    manifest_ids = {item.doc_id for item in manifest.documents}
    evidence_ids = [item.evidence_id for item in evidence]
    event_keys = [item.event_key for item in events]
    report_citation_ids = {
        evidence_id
        for item in report.citations
        for evidence_id in (item.evidence_ids or [item.evidence_id])
    }
    report_evidence_ids = set(report.evidence_ids)
    citation_coverage = (
        len(report_evidence_ids & report_citation_ids) / len(report_evidence_ids)
        if report_evidence_ids
        else 1.0
    )
    unsupported_in_report = 0
    for result in verifications:
        claim = claims.get(result.claim_id)
        if (
            claim is not None
            and result.status == ClaimVerificationStatus.UNSUPPORTED
            and claim.claim_text in report.markdown
        ):
            unsupported_in_report += 1

    progress = ResearchProgressService(repository).get_progress(research_id)
    source_violations = sum(item.doc_id not in manifest_ids for item in evidence)
    known_evidence_ids = set(evidence_ids)
    broken_citations = sum(
        evidence_id not in known_evidence_ids
        for item in report.citations
        for evidence_id in (item.evidence_ids or [item.evidence_id])
    )
    duplicate_evidence = len(evidence_ids) - len(set(evidence_ids))
    duplicate_events = len(event_keys) - len(set(event_keys))
    passed = all(
        (
            source_violations == 0,
            citation_coverage == 1.0,
            broken_citations == 0,
            unsupported_in_report == 0,
            duplicate_evidence == 0,
            duplicate_events == 0,
        )
    )
    return ResearchQualityBaseline(
        research_id=research_id,
        result_status=job.result_status,
        source_scope_violations=source_violations,
        citation_coverage=citation_coverage,
        broken_citations=broken_citations,
        unsupported_claims_in_report=unsupported_in_report,
        duplicate_evidence_ids=duplicate_evidence,
        duplicate_event_keys=duplicate_events,
        conflict_count=len(report.conflicts),
        limitation_count=len(report.limitations),
        evidence_count=len(evidence),
        action_count=progress.metrics.actions_used,
        tool_call_count=progress.metrics.tool_calls,
        recovery_count=progress.metrics.recovery_count,
        elapsed_ms=progress.metrics.elapsed_ms,
        passed=passed,
    )


__all__ = ["ResearchQualityBaseline", "evaluate_research_run"]
