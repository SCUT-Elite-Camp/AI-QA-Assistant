"""Durable, version-bound messages between independent Research roles."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, model_validator
from agent.schemas.research import ResearchContractModel, ResearchReport


def report_digest(report: ResearchReport) -> str:
    payload = report.model_dump(mode="json", exclude={
        "generated_at", "review_status", "review_id", "coordinator_approved",
    })
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AgentResult(ResearchContractModel):
    agent_id: str
    research_id: str
    role: Literal["explorer", "repair"]
    task_id: str
    status: Literal["succeeded", "failed", "blocked"]
    finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    actions_used: int = 0
    error_code: str | None = None


class AgentStep(ResearchContractModel):
    step_id: str
    research_id: str
    agent_id: str
    role: Literal["explorer", "repair", "reviewer", "coordinator"]
    task_id: str | None = None
    action: str
    evidence_ids: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)


class ReportDraft(ResearchContractModel):
    draft_id: str
    research_id: str
    plan_version: int
    revision: int = Field(ge=1)
    report: ResearchReport
    report_hash: str
    author_agent_id: str
    parent_draft_id: str | None = None

    @model_validator(mode="after")
    def bound_content(self):
        if (self.report.research_id != self.research_id or self.report.revision != self.revision
                or report_digest(self.report) != self.report_hash):
            raise ValueError("research_draft_binding_mismatch")
        return self


class ReviewIssue(ResearchContractModel):
    issue_id: str
    kind: Literal["unsupported", "citation", "coverage", "contradiction", "structure"]
    description: str = Field(min_length=1, max_length=2000)
    suggestion: str = Field(min_length=1, max_length=2000)
    block_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)


class ReportReview(ResearchContractModel):
    review_id: str
    research_id: str
    draft_id: str
    revision: int
    report_hash: str
    reviewer_agent_id: str
    status: Literal["passed", "not_passed"]
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=100)
    checked_citation_numbers: list[int] = Field(default_factory=list, max_length=200)
    checked_block_ids: list[int] = Field(default_factory=list, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def consistent_verdict(self):
        if (self.status == "passed") != (not self.issues):
            raise ValueError("review_verdict_issues_mismatch")
        return self


class CoordinatorApproval(ResearchContractModel):
    approval_id: str
    research_id: str
    draft_id: str
    report_hash: str
    review_id: str
    approved: bool
    issues: list[str] = Field(default_factory=list)
