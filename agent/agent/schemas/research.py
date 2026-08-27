"""Contracts for the manually-triggered, Local Research flow.

The original ``research.v1`` models remain compatible with the Week 1
fixtures.  The runtime objects added below are the smallest v2 control-plane
contracts required by the Core Vertical Slice: a durable Job owns one frozen
SourceManifest and one versioned Plan, and an Approval binds both before a
future Worker may execute.

This module still contains data contracts and deterministic validation only.
It does not access the network or silently expand a research source scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESEARCH_SCHEMA_VERSION = "research.v1"
RESEARCH_RUNTIME_SCHEMA_VERSION = "research.v2"

# The Week 1 contract is deliberately Local-only and read-only.  This allowlist
# is the first boundary that prevents a future Planner from smuggling in a
# network or write tool through a plan payload.
LOCAL_RESEARCH_TOOLS = frozenset(
    {
        "list_documents",
        "get_document_outline",
        "keyword_search",
        "semantic_search",
        "read_document_range",
    }
)


class ResearchProfile(StrEnum):
    """Research profiles available in the CP2 MVP."""

    STANDARD = "standard"


class ResearchPlanStatus(StrEnum):
    """Lifecycle values accepted by the contract before runtime execution."""

    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class ResearchJobStatus(StrEnum):
    """Small execution state machine shared by the API and the dispatcher."""

    CREATED = "created"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchResultStatus(StrEnum):
    """Quality of a successfully completed workflow, separate from lifecycle."""

    COMPLETE = "complete"
    DEGRADED = "degraded"


class ResearchTaskPriority(StrEnum):
    CRITICAL = "critical"
    NORMAL = "normal"
    OPTIONAL = "optional"


class ResearchTaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ResearchContractModel(BaseModel):
    """Shared strict configuration for all CP2 Research contracts."""

    model_config = ConfigDict(extra="forbid")


def _normalize_unique_strings(values: list[str], field_name: str) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must contain strings")
        item = " ".join(value.strip().split())
        if not item:
            raise ValueError(f"{field_name} must not contain empty values")
        if item not in normalized:
            normalized.append(item)
    return normalized


def _validate_local_identifier(value: str, field_name: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    lowered = normalized.lower()
    if "://" in normalized or lowered.startswith(("http:", "https:", "www.")):
        raise ValueError("source_scope_external_source_forbidden")
    return normalized


class SourceScope(ResearchContractModel):
    """Explicitly allowlisted local knowledge sources for one research run."""

    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=20)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    topic: str = Field(default="", max_length=200)

    @field_validator("knowledge_base_ids", "document_ids")
    @classmethod
    def normalize_source_ids(cls, values: list[str], info) -> list[str]:
        normalized = _normalize_unique_strings(values, info.field_name)
        return [_validate_local_identifier(value, info.field_name) for value in normalized]

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        return " ".join(value.strip().split())

    def allowed_source_ids(self) -> frozenset[str]:
        """Return explicit identifiers that a task may narrow to."""

        return frozenset((*self.knowledge_base_ids, *self.document_ids))

    def has_explicit_scope(self) -> bool:
        return bool(self.knowledge_base_ids or self.document_ids or self.topic)


class ReportSpec(ResearchContractModel):
    """Output constraints for the CP2 Markdown research report."""

    format: Literal["markdown"] = "markdown"
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    title: str = Field(default="", max_length=200)
    sections: list[str] = Field(default_factory=list, max_length=20)
    include_citations: bool = True
    include_limitations: bool = True

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, values: list[str]) -> list[str]:
        return _normalize_unique_strings(values, "sections")


class ResearchRequest(ResearchContractModel):
    """User-supplied request for a manually started Local Research run."""

    schema_version: Literal[RESEARCH_SCHEMA_VERSION, RESEARCH_RUNTIME_SCHEMA_VERSION] = (
        RESEARCH_SCHEMA_VERSION
    )
    query: str = Field(min_length=1, max_length=4000)
    source_scope: SourceScope
    report_spec: ReportSpec = Field(default_factory=ReportSpec)
    profile: ResearchProfile = ResearchProfile.STANDARD
    user_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("research_query_empty")
        return normalized

    @field_validator("user_notes")
    @classmethod
    def normalize_user_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_explicit_source_scope(self) -> "ResearchRequest":
        if not self.source_scope.has_explicit_scope():
            raise ValueError("research_source_scope_required")
        return self


class ResearchBudget(ResearchContractModel):
    """Hard limits owned by the runtime, never by model output."""

    max_tasks: int = Field(default=8, ge=1, le=20)
    max_actions: int = Field(default=32, ge=1, le=100)
    max_tool_calls: int = Field(default=32, ge=1, le=100)
    max_tokens: int = Field(default=20_000, ge=1_000, le=100_000)
    max_runtime_seconds: int = Field(default=300, ge=10, le=1_800)


class AcceptanceCriterion(ResearchContractModel):
    """One deterministic condition used to decide whether a task is complete."""

    criterion_id: str = Field(min_length=1, max_length=80)
    # ``description`` and ``requires_evidence`` are retained for v1 fixture
    # compatibility.  v2 callers should prefer the structured dimension /
    # target / required fields below.
    description: str = Field(default="", max_length=500)
    requires_evidence: bool = True
    dimension: str = Field(default="general", min_length=1, max_length=80)
    target: str = Field(default="", max_length=200)
    required: bool = True

    @field_validator("criterion_id", "dimension", "target", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized and value:
            raise ValueError("acceptance_criterion_empty")
        return normalized

    @model_validator(mode="after")
    def normalize_structured_fields(self) -> "AcceptanceCriterion":
        """Allow old descriptive fixtures while exposing a deterministic v2 shape."""

        if not self.target and self.description:
            self.target = self.description
        if not self.description and self.target:
            self.description = f"{self.dimension}: {self.target}"
        if not self.target and not self.description:
            raise ValueError("acceptance_criterion_empty")
        return self


class ResearchTask(ResearchContractModel):
    """One bounded, read-only research task in a plan."""

    task_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(min_length=1, max_length=500)
    dependencies: list[str] = Field(default_factory=list, max_length=20)
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["keyword_search", "read_document_range"],
        max_length=10,
    )
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list, max_length=10)
    priority: ResearchTaskPriority = ResearchTaskPriority.NORMAL
    max_actions: int = Field(default=4, ge=1, le=50)
    status: ResearchTaskStatus = ResearchTaskStatus.PENDING

    @field_validator("task_id", "question", "purpose")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("research_task_text_empty")
        return normalized

    @field_validator("dependencies", "allowed_tools", "source_ids")
    @classmethod
    def normalize_lists(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class ResearchPlan(ResearchContractModel):
    """Versioned Planner output consumed by the future Research runtime."""

    schema_version: Literal[RESEARCH_SCHEMA_VERSION, RESEARCH_RUNTIME_SCHEMA_VERSION] = (
        RESEARCH_SCHEMA_VERSION
    )
    research_id: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1, le=1000)
    objective: str = Field(min_length=1, max_length=4000)
    out_of_scope: list[str] = Field(default_factory=list, max_length=20)
    source_scope: SourceScope
    report_spec: ReportSpec = Field(default_factory=ReportSpec)
    manifest_hash: str | None = Field(default=None, min_length=8, max_length=128)
    tasks: list[ResearchTask] = Field(default_factory=list, max_length=20)
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    status: ResearchPlanStatus = ResearchPlanStatus.DRAFT

    @field_validator("research_id", "objective")
    @classmethod
    def normalize_plan_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("research_plan_text_empty")
        return normalized

    @field_validator("out_of_scope")
    @classmethod
    def normalize_out_of_scope(cls, values: list[str]) -> list[str]:
        return _normalize_unique_strings(values, "out_of_scope")


class SourceManifestDocument(ResearchContractModel):
    """One immutable local document snapshot allowed in a Research Job."""

    doc_id: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=200)
    content_hash: str = Field(min_length=8, max_length=128)

    @field_validator("doc_id", "version", "content_hash")
    @classmethod
    def normalize_manifest_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("source_manifest_value_empty")
        return normalized


class SourceManifest(ResearchContractModel):
    """Frozen source set used by Planning and all later execution stages."""

    schema_version: Literal[RESEARCH_RUNTIME_SCHEMA_VERSION] = (
        RESEARCH_RUNTIME_SCHEMA_VERSION
    )
    research_id: str = Field(min_length=1, max_length=100)
    documents: list[SourceManifestDocument] = Field(min_length=1, max_length=100)
    manifest_hash: str = Field(min_length=8, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_unique_documents(self) -> "SourceManifest":
        doc_ids = [document.doc_id for document in self.documents]
        if len(doc_ids) != len(set(doc_ids)):
            raise ValueError("source_manifest_duplicate_document_id")
        if self.manifest_hash != self.calculate_hash(self.documents):
            raise ValueError("source_manifest_hash_mismatch")
        return self

    @staticmethod
    def calculate_hash(documents: Iterable[SourceManifestDocument]) -> str:
        """Calculate the canonical hash used by Approval snapshots."""

        payload = [
            {
                "doc_id": document.doc_id,
                "version": document.version,
                "content_hash": document.content_hash,
            }
            for document in sorted(documents, key=lambda item: item.doc_id)
        ]
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_documents(
        cls,
        research_id: str,
        documents: Iterable[SourceManifestDocument],
    ) -> "SourceManifest":
        """Build a stable hash from document identity and version metadata."""

        ordered = sorted(documents, key=lambda document: document.doc_id)
        if not ordered:
            raise ValueError("source_manifest_empty")
        manifest_hash = cls.calculate_hash(ordered)
        return cls(
            research_id=research_id,
            documents=ordered,
            manifest_hash=manifest_hash,
        )


class ResearchApproval(ResearchContractModel):
    """Auditable approval snapshot binding one Plan to one Manifest."""

    schema_version: Literal[RESEARCH_RUNTIME_SCHEMA_VERSION] = (
        RESEARCH_RUNTIME_SCHEMA_VERSION
    )
    research_id: str = Field(min_length=1, max_length=100)
    plan_version: int = Field(ge=1)
    manifest_hash: str = Field(min_length=8, max_length=128)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("approved_by")
    @classmethod
    def normalize_approver(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("research_approval_actor_required")
        return normalized


class Observation(ResearchContractModel):
    """A search observation that has not yet been promoted to evidence."""

    observation_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=80)
    tool_name: str = Field(min_length=1, max_length=100)
    doc_id: str | None = Field(default=None, max_length=200)
    locator_hint: str | None = Field(default=None, max_length=300)
    snippet: str = Field(min_length=1, max_length=10_000)
    query: str = Field(min_length=1, max_length=2_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerifiedEvidence(ResearchContractModel):
    """Original-source excerpt with a stable location inside the Manifest."""

    evidence_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=80)
    doc_id: str = Field(min_length=1, max_length=200)
    document_version: str | None = Field(default=None, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=20_000)
    content_hash: str = Field(min_length=8, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Finding(ResearchContractModel):
    """A bounded research finding backed by persisted Evidence IDs."""

    finding_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    covers: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_ids", "covers")
    @classmethod
    def normalize_finding_ids(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class CriterionCoverage(ResearchContractModel):
    """Deterministic result for one required or optional criterion."""

    criterion_id: str = Field(min_length=1, max_length=80)
    covered: bool
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_ids")
    @classmethod
    def normalize_coverage_ids(cls, values: list[str]) -> list[str]:
        return _normalize_unique_strings(values, "evidence_ids")


class CoverageResult(ResearchContractModel):
    """Basic criterion coverage, intentionally not a multidimensional matrix."""

    research_id: str = Field(min_length=1, max_length=100)
    covered: list[str] = Field(default_factory=list, max_length=100)
    missing: list[str] = Field(default_factory=list, max_length=100)
    sufficient: bool
    criteria: list[CriterionCoverage] = Field(default_factory=list, max_length=100)

    @field_validator("covered", "missing")
    @classmethod
    def normalize_coverage_criteria(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class ClaimVerificationStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"


class ClaimDraft(ResearchContractModel):
    """A factual statement that must be verified before rendering."""

    claim_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    criterion_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_ids", "criterion_ids")
    @classmethod
    def normalize_claim_ids(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class VerificationResult(ResearchContractModel):
    """Structural and semantic verification result for one ClaimDraft."""

    claim_id: str = Field(min_length=1, max_length=100)
    status: ClaimVerificationStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=2_000)

    @field_validator("evidence_ids")
    @classmethod
    def normalize_verification_ids(cls, values: list[str]) -> list[str]:
        return _normalize_unique_strings(values, "evidence_ids")


class VerifiedClaim(ResearchContractModel):
    """ClaimDraft enriched with its verification outcome for the Renderer."""

    claim_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=4_000)
    status: ClaimVerificationStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    criterion_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=2_000)

    @field_validator("evidence_ids", "criterion_ids")
    @classmethod
    def normalize_verified_claim_ids(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class ResearchReport(ResearchContractModel):
    """Persisted Markdown output produced only from verified Claims."""

    report_id: str = Field(min_length=1, max_length=100)
    research_id: str = Field(min_length=1, max_length=100)
    markdown: str = Field(min_length=1, max_length=100_000)
    result_status: ResearchResultStatus
    claim_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("claim_ids", "evidence_ids")
    @classmethod
    def normalize_report_ids(cls, values: list[str], info) -> list[str]:
        return _normalize_unique_strings(values, info.field_name)


class ResearchJob(ResearchContractModel):
    """Durable business state for one manually started Local Research run."""

    schema_version: Literal[RESEARCH_RUNTIME_SCHEMA_VERSION] = (
        RESEARCH_RUNTIME_SCHEMA_VERSION
    )
    research_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=200)
    request: ResearchRequest
    status: ResearchJobStatus = ResearchJobStatus.CREATED
    result_status: ResearchResultStatus | None = None
    plan_version: int | None = Field(default=None, ge=1)
    manifest_hash: str | None = Field(default=None, min_length=8, max_length=128)
    current_stage: str = Field(default="created", min_length=1, max_length=80)
    current_task_id: str | None = Field(default=None, max_length=80)
    task_total: int = Field(default=0, ge=0)
    task_completed: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    failure_stage: str | None = Field(default=None, max_length=80)
    error_code: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("user_id", "current_stage", "current_task_id", "failure_stage", "error_code")
    @classmethod
    def normalize_job_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("research_job_value_empty")
        return normalized


@dataclass(frozen=True)
class PlanIssue:
    """Stable, machine-readable Planner validation issue."""

    code: str
    path: str
    message: str


class ResearchPlanValidationError(ValueError):
    """Raised when a syntactically valid plan violates deterministic rules."""

    def __init__(self, issue: PlanIssue) -> None:
        self.code = issue.code
        self.path = issue.path
        self.issue = issue
        super().__init__(f"{issue.code} at {issue.path}: {issue.message}")


class ResearchPlanValidator:
    """Deterministic v1 plan validator with stable error codes."""

    @classmethod
    def validate(cls, plan: ResearchPlan) -> list[PlanIssue]:
        issues: list[PlanIssue] = []
        tasks = plan.tasks

        if not tasks:
            issues.append(
                PlanIssue(
                    "research_plan_empty_tasks",
                    "tasks",
                    "a research plan must contain at least one task",
                )
            )
            return issues

        if len(tasks) > plan.budget.max_tasks:
            issues.append(
                PlanIssue(
                    "research_plan_task_budget_exceeded",
                    "tasks",
                    "task count exceeds budget.max_tasks",
                )
            )

        task_ids = [task.task_id for task in tasks]
        duplicate_ids = cls._duplicates(task_ids)
        for task_id in duplicate_ids:
            issues.append(
                PlanIssue(
                    "research_plan_duplicate_task_id",
                    "tasks",
                    f"task id '{task_id}' appears more than once",
                )
            )

        normalized_questions = [cls._normalize_question(task.question) for task in tasks]
        for left_index, left in enumerate(normalized_questions):
            for right_index in range(left_index + 1, len(normalized_questions)):
                right = normalized_questions[right_index]
                if left == right or SequenceMatcher(None, left, right).ratio() >= 0.95:
                    issues.append(
                        PlanIssue(
                            "research_plan_duplicate_task_question",
                            f"tasks[{right_index}].question",
                            "task question is materially duplicated",
                        )
                    )

        known_ids = set(task_ids)
        for index, task in enumerate(tasks):
            missing_dependencies = sorted(set(task.dependencies) - known_ids)
            if missing_dependencies:
                issues.append(
                    PlanIssue(
                        "research_plan_unknown_dependency",
                        f"tasks[{index}].dependencies",
                        f"unknown task id(s): {', '.join(missing_dependencies)}",
                    )
                )

            unauthorized_tools = sorted(
                set(task.allowed_tools) - LOCAL_RESEARCH_TOOLS
            )
            if unauthorized_tools:
                issues.append(
                    PlanIssue(
                        "research_task_tool_not_allowed",
                        f"tasks[{index}].allowed_tools",
                        f"tool(s) are outside the Local Research allowlist: {', '.join(unauthorized_tools)}",
                    )
                )

            scope_ids = plan.source_scope.allowed_source_ids()
            out_of_scope_ids = sorted(set(task.source_ids) - scope_ids)
            if out_of_scope_ids:
                issues.append(
                    PlanIssue(
                        "research_task_source_out_of_scope",
                        f"tasks[{index}].source_ids",
                        f"source id(s) are outside the plan scope: {', '.join(out_of_scope_ids)}",
                    )
                )

            if not task.acceptance_criteria:
                issues.append(
                    PlanIssue(
                        "research_task_acceptance_criteria_missing",
                        f"tasks[{index}].acceptance_criteria",
                        "each task needs at least one acceptance criterion",
                    )
                )

        total_actions = sum(task.max_actions for task in tasks)
        if total_actions > plan.budget.max_actions:
            issues.append(
                PlanIssue(
                    "research_plan_action_budget_exceeded",
                    "budget.max_actions",
                    "sum of task max_actions exceeds budget.max_actions",
                )
            )

        cycle = cls._find_dependency_cycle(tasks)
        if cycle:
            issues.append(
                PlanIssue(
                    "research_plan_dependency_cycle",
                    "tasks.dependencies",
                    f"dependency cycle detected: {' -> '.join(cycle)}",
                )
            )

        if not plan.report_spec.include_citations:
            issues.append(
                PlanIssue(
                    "research_report_citations_required",
                    "report_spec.include_citations",
                    "CP2 reports must retain evidence citations",
                )
            )

        return issues

    @classmethod
    def validate_or_raise(cls, plan: ResearchPlan) -> ResearchPlan:
        issues = cls.validate(plan)
        if issues:
            raise ResearchPlanValidationError(issues[0])
        if not plan.source_scope.has_explicit_scope():
            issue = PlanIssue(
                "research_source_scope_required",
                "source_scope",
                "source scope must name a knowledge base, document, or topic",
            )
            raise ResearchPlanValidationError(issue)
        return plan

    @classmethod
    def topological_sort(
        cls,
        plan_or_tasks: ResearchPlan | list[ResearchTask],
    ) -> list[ResearchTask]:
        """Return a stable dependency order for the single Worker runtime.

        The order preserves the Planner's task order whenever multiple tasks
        are ready.  This is deliberately only a topological sort; it does not
        introduce a parallel scheduler.
        """

        tasks = (
            plan_or_tasks.tasks
            if isinstance(plan_or_tasks, ResearchPlan)
            else plan_or_tasks
        )
        task_map = {task.task_id: task for task in tasks}
        indegree = {task.task_id: len(task.dependencies) for task in tasks}
        children: dict[str, list[str]] = {task.task_id: [] for task in tasks}
        for task in tasks:
            for dependency in task.dependencies:
                if dependency in children:
                    children[dependency].append(task.task_id)

        ready = [task.task_id for task in tasks if indegree[task.task_id] == 0]
        ordered_ids: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered_ids.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

        if len(ordered_ids) != len(tasks):
            cycle = cls._find_dependency_cycle(tasks)
            issue = PlanIssue(
                "research_plan_dependency_cycle",
                "tasks.dependencies",
                f"dependency cycle detected: {' -> '.join(cycle)}",
            )
            raise ResearchPlanValidationError(issue)
        return [task_map[task_id] for task_id in ordered_ids]

    @staticmethod
    def _duplicates(values: list[str]) -> list[str]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for value in values:
            if value in seen and value not in duplicates:
                duplicates.append(value)
            seen.add(value)
        return duplicates

    @staticmethod
    def _normalize_question(value: str) -> str:
        return re.sub(r"[\s？?!。,.，、:：；;]+", "", value.lower())

    @staticmethod
    def _find_dependency_cycle(tasks: list[ResearchTask]) -> list[str]:
        graph = {task.task_id: task.dependencies for task in tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str, path: list[str]) -> list[str]:
            if task_id in visiting:
                cycle_start = path.index(task_id)
                return path[cycle_start:] + [task_id]
            if task_id in visited:
                return []

            visiting.add(task_id)
            for dependency in graph.get(task_id, []):
                cycle = visit(dependency, path + [task_id])
                if cycle:
                    return cycle
            visiting.remove(task_id)
            visited.add(task_id)
            return []

        for task_id in graph:
            cycle = visit(task_id, [])
            if cycle:
                return cycle
        return []


__all__ = [
    "AcceptanceCriterion",
    "ClaimDraft",
    "ClaimVerificationStatus",
    "CriterionCoverage",
    "CoverageResult",
    "Finding",
    "LOCAL_RESEARCH_TOOLS",
    "Observation",
    "PlanIssue",
    "ReportSpec",
    "ResearchBudget",
    "ResearchContractModel",
    "ResearchApproval",
    "ResearchJob",
    "ResearchPlan",
    "ResearchPlanStatus",
    "ResearchPlanValidationError",
    "ResearchPlanValidator",
    "ResearchJobStatus",
    "ResearchResultStatus",
    "ResearchReport",
    "ResearchProfile",
    "ResearchRequest",
    "ResearchTask",
    "ResearchTaskPriority",
    "ResearchTaskStatus",
    "SourceManifest",
    "SourceManifestDocument",
    "SourceScope",
    "VerificationResult",
    "VerifiedEvidence",
    "VerifiedClaim",
    "RESEARCH_SCHEMA_VERSION",
    "RESEARCH_RUNTIME_SCHEMA_VERSION",
]
