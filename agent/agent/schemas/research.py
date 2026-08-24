"""Versioned contracts for the manually-triggered, Local Research flow.

This module intentionally contains contracts and deterministic validation only.
It does not create jobs, call an LLM, access the web, or execute tools.  The
Research runtime will consume these models in a later week after the manual
entry point and approval flow are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESEARCH_SCHEMA_VERSION = "research.v1"

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

    schema_version: Literal[RESEARCH_SCHEMA_VERSION] = RESEARCH_SCHEMA_VERSION
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
    description: str = Field(min_length=1, max_length=500)
    requires_evidence: bool = True

    @field_validator("criterion_id", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("acceptance_criterion_empty")
        return normalized


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

    schema_version: Literal[RESEARCH_SCHEMA_VERSION] = RESEARCH_SCHEMA_VERSION
    research_id: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1, le=1000)
    objective: str = Field(min_length=1, max_length=4000)
    out_of_scope: list[str] = Field(default_factory=list, max_length=20)
    source_scope: SourceScope
    report_spec: ReportSpec = Field(default_factory=ReportSpec)
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
    "LOCAL_RESEARCH_TOOLS",
    "PlanIssue",
    "ReportSpec",
    "ResearchBudget",
    "ResearchContractModel",
    "ResearchPlan",
    "ResearchPlanStatus",
    "ResearchPlanValidationError",
    "ResearchPlanValidator",
    "ResearchProfile",
    "ResearchRequest",
    "ResearchTask",
    "ResearchTaskPriority",
    "ResearchTaskStatus",
    "SourceScope",
    "RESEARCH_SCHEMA_VERSION",
]
