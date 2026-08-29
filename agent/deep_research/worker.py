"""Bounded single-Worker strategy for Local Deep Research.

This module owns the research decision policy, not persistence infrastructure.
The Worker accepts an :class:`ApprovedResearchContext`, so it cannot start
from a loose query or an unapproved model-generated plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Callable, Iterable, Mapping, Protocol
import uuid

from agent.schemas.research import (
    Finding,
    Observation,
    ResearchJobStatus,
    ResearchPlanStatus,
    ResearchTask,
    ResearchTaskStatus,
    SourceManifest,
    VerifiedEvidence,
)

from .service import ApprovedResearchContext


class ResearchToolError(RuntimeError):
    """A local Search or Original Read action failed."""


@dataclass(frozen=True)
class SearchHit:
    """Normalized candidate returned by a local Search adapter."""

    doc_id: str
    snippet: str
    locator_hint: str | None = None
    document_version: str | None = None
    score: float | None = None

    @classmethod
    def from_value(cls, value: "SearchHit | Mapping[str, Any]") -> "SearchHit":
        if isinstance(value, cls):
            return value
        doc_id = str(value.get("doc_id") or "").strip()
        if not doc_id:
            raise ResearchToolError("search result is missing doc_id")
        snippet = str(
            value.get("snippet")
            or value.get("chunk_text")
            or value.get("text")
            or value.get("content")
            or ""
        ).strip()
        locator = value.get("locator") or value.get("locator_hint")
        if locator is None:
            locator = value.get("chunk_id")
        if locator is None and value.get("chunk_index") is not None:
            locator = f"chunk:{value['chunk_index']}"
        version = value.get("document_version") or value.get("version")
        return cls(
            doc_id=doc_id,
            snippet=snippet,
            locator_hint=str(locator) if locator is not None else None,
            document_version=str(version) if version is not None else None,
            score=float(value["score"]) if value.get("score") is not None else None,
        )


@dataclass(frozen=True)
class OriginalRead:
    """Normalized original-document range returned by a local Read adapter."""

    doc_id: str
    locator: str
    excerpt: str
    document_version: str | None = None
    content_hash: str | None = None

    @classmethod
    def from_value(cls, value: "OriginalRead | Mapping[str, Any]") -> "OriginalRead":
        if isinstance(value, cls):
            return value
        doc_id = str(value.get("doc_id") or "").strip()
        locator = str(value.get("locator") or value.get("location") or "").strip()
        excerpt = str(
            value.get("excerpt")
            or value.get("content")
            or value.get("text")
            or ""
        ).strip()
        if not doc_id or not locator or not excerpt:
            raise ResearchToolError(
                "original read must include doc_id, locator and non-empty excerpt"
            )
        version = value.get("document_version") or value.get("version")
        content_hash = value.get("content_hash")
        return cls(
            doc_id=doc_id,
            locator=locator,
            excerpt=excerpt,
            document_version=str(version) if version is not None else None,
            content_hash=str(content_hash) if content_hash else None,
        )


class LocalResearchTools(Protocol):
    """B-side adapter required by the A-side Worker policy."""

    def search(
        self,
        *,
        query: str,
        source_ids: list[str],
        research_id: str,
        task_id: str,
        trace_id: str,
    ) -> Iterable[SearchHit | Mapping[str, Any]]:
        """Return candidate locations, never authoritative Evidence."""

    def read_document_range(
        self,
        *,
        doc_id: str,
        locator_hint: str,
        research_id: str,
        task_id: str,
        trace_id: str,
    ) -> OriginalRead | Mapping[str, Any]:
        """Return the original text at a stable location."""


class ObservationSink(Protocol):
    def save_observation(self, observation: Observation) -> None:
        """Persist a Search Observation."""


class EvidenceSink(Protocol):
    def save_evidence(self, evidence: VerifiedEvidence) -> None:
        """Persist a Verified Evidence item."""


class FindingSink(Protocol):
    def save_finding(self, finding: Finding) -> None:
        """Persist a bounded Finding."""


class ResearchLedger(ObservationSink, EvidenceSink, FindingSink, Protocol):
    pass


@dataclass
class InMemoryResearchLedger:
    """Small deterministic ledger for A-side tests and local demos.

    B's SQLite Evidence Ledger can implement the same three sink methods.  It
    is intentionally not used as the production Repository implementation.
    """

    observations: list[Observation] = field(default_factory=list)
    evidence: dict[str, VerifiedEvidence] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def save_observation(self, observation: Observation) -> None:
        self.observations.append(observation)

    def save_evidence(self, evidence: VerifiedEvidence) -> None:
        self.evidence.setdefault(evidence.evidence_id, evidence)

    def save_finding(self, finding: Finding) -> None:
        self.findings.append(finding)


@dataclass(frozen=True)
class TaskExecutionResult:
    task_id: str
    status: ResearchTaskStatus
    actions_used: int
    observation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    stop_reason: str = ""


@dataclass(frozen=True)
class ResearchRunResult:
    research_id: str
    task_results: tuple[TaskExecutionResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(
            result.status == ResearchTaskStatus.SUCCEEDED
            for result in self.task_results
        )


CriterionMapper = Callable[[ResearchTask, VerifiedEvidence], list[str]]
FindingBuilder = Callable[
    [ApprovedResearchContext, ResearchTask, list[VerifiedEvidence], list[str]], Finding
]


class ConservativeCriterionMapper:
    """Map only criteria with an observable relationship to read evidence."""

    def __call__(self, task: ResearchTask, evidence: VerifiedEvidence) -> list[str]:
        excerpt = evidence.excerpt.casefold()
        covered: list[str] = []
        for criterion in task.acceptance_criteria:
            target = criterion.target.casefold().strip()
            if criterion.dimension == "evidence" and excerpt:
                covered.append(criterion.criterion_id)
            elif criterion.dimension == "locator" and evidence.locator:
                covered.append(criterion.criterion_id)
            elif target and target in excerpt:
                covered.append(criterion.criterion_id)
            elif criterion.dimension == "limitation" and any(
                marker in excerpt for marker in ("限制", "缺少", "无法", "未提供", "not available")
            ):
                covered.append(criterion.criterion_id)
        return covered


class LocalResearchWorker:
    """Execute each approved Task with one bounded Search→Read loop."""

    def __init__(
        self,
        tools: LocalResearchTools,
        ledger: ResearchLedger | None = None,
        *,
        max_candidates_per_task: int = 2,
        criterion_mapper: CriterionMapper | None = None,
        finding_builder: FindingBuilder | None = None,
        trace_id_factory: Callable[[str], str] | None = None,
    ) -> None:
        if max_candidates_per_task < 1:
            raise ValueError("max_candidates_per_task must be positive")
        self.tools = tools
        self.ledger = ledger or InMemoryResearchLedger()
        self.max_candidates_per_task = max_candidates_per_task
        self.criterion_mapper = criterion_mapper or ConservativeCriterionMapper()
        self.finding_builder = finding_builder or self._default_finding_builder
        self.trace_id_factory = trace_id_factory or (
            lambda research_id: f"research-{research_id}"
        )

    def run(self, context: ApprovedResearchContext) -> ResearchRunResult:
        """Run the real approved context in stable dependency order."""

        self._validate_context(context)
        ordered_tasks = self._ordered_context_tasks(context)
        outcomes: dict[str, TaskExecutionResult] = {}

        for task in ordered_tasks:
            blocked_dependency = next(
                (
                    dependency
                    for dependency in task.dependencies
                    if outcomes.get(dependency) is None
                    or outcomes[dependency].status != ResearchTaskStatus.SUCCEEDED
                ),
                None,
            )
            if blocked_dependency is not None:
                outcomes[task.task_id] = TaskExecutionResult(
                    task_id=task.task_id,
                    status=ResearchTaskStatus.BLOCKED,
                    actions_used=0,
                    stop_reason=f"dependency_not_succeeded:{blocked_dependency}",
                )
                continue
            outcomes[task.task_id] = self._execute_task(context, task)

        # Keep output in the same deterministic order as the validated plan.
        return ResearchRunResult(
            research_id=context.job.research_id,
            task_results=tuple(outcomes[task.task_id] for task in ordered_tasks),
        )

    execute = run

    def _execute_task(
        self,
        context: ApprovedResearchContext,
        task: ResearchTask,
    ) -> TaskExecutionResult:
        manifest_ids = {document.doc_id for document in context.manifest.documents}
        requested_ids = task.source_ids or sorted(manifest_ids)
        if set(requested_ids) - manifest_ids:
            return TaskExecutionResult(
                task_id=task.task_id,
                status=ResearchTaskStatus.FAILED,
                actions_used=0,
                stop_reason="task_source_out_of_manifest",
            )

        trace_id = self.trace_id_factory(context.job.research_id)
        actions_used = 1
        observation_ids: list[str] = []
        evidence_ids: list[str] = []
        finding_ids: list[str] = []
        verified: list[VerifiedEvidence] = []
        try:
            raw_hits = self.tools.search(
                query=task.question,
                source_ids=list(requested_ids),
                research_id=context.job.research_id,
                task_id=task.task_id,
                trace_id=trace_id,
            )
            hits = [SearchHit.from_value(value) for value in raw_hits]
        except Exception as exc:
            return TaskExecutionResult(
                task_id=task.task_id,
                status=ResearchTaskStatus.FAILED,
                actions_used=actions_used,
                stop_reason=f"search_failed:{exc.__class__.__name__}",
            )

        for index, hit in enumerate(hits[: self.max_candidates_per_task]):
            observation = Observation(
                observation_id=self._new_id("observation", task.task_id, index),
                research_id=context.job.research_id,
                task_id=task.task_id,
                tool_name="search",
                doc_id=hit.doc_id,
                locator_hint=hit.locator_hint,
                snippet=hit.snippet or "search result without snippet",
                query=task.question,
            )
            self.ledger.save_observation(observation)
            observation_ids.append(observation.observation_id)

            if actions_used >= task.max_actions:
                break
            if hit.doc_id not in manifest_ids:
                continue
            if not hit.locator_hint:
                continue

            actions_used += 1
            try:
                original = OriginalRead.from_value(
                    self.tools.read_document_range(
                        doc_id=hit.doc_id,
                        locator_hint=hit.locator_hint,
                        research_id=context.job.research_id,
                        task_id=task.task_id,
                        trace_id=trace_id,
                    )
                )
            except Exception:
                continue
            if original.doc_id not in manifest_ids:
                continue

            manifest_document = next(
                document
                for document in context.manifest.documents
                if document.doc_id == original.doc_id
            )
            evidence = VerifiedEvidence(
                evidence_id=self._new_id("evidence", task.task_id, len(verified)),
                research_id=context.job.research_id,
                task_id=task.task_id,
                doc_id=original.doc_id,
                document_version=original.document_version or manifest_document.version,
                locator=original.locator,
                excerpt=original.excerpt,
                content_hash=original.content_hash
                or hashlib.sha256(original.excerpt.encode("utf-8")).hexdigest(),
            )
            self.ledger.save_evidence(evidence)
            verified.append(evidence)
            evidence_ids.append(evidence.evidence_id)

            # Stop after a complete, bounded evidence unit.  A comparison task
            # may still read the next hit up to its explicit action limit.
            if actions_used >= task.max_actions:
                break

        if not verified:
            reason = "no_verified_evidence"
            if hits and actions_used >= task.max_actions:
                reason = "action_budget_exhausted_before_original_read"
            return TaskExecutionResult(
                task_id=task.task_id,
                status=ResearchTaskStatus.FAILED,
                actions_used=actions_used,
                observation_ids=tuple(observation_ids),
                stop_reason=reason,
            )

        covers = sorted(
            {
                criterion_id
                for evidence in verified
                for criterion_id in self.criterion_mapper(task, evidence)
            }
        )
        finding = self.finding_builder(context, task, verified, covers)
        self.ledger.save_finding(finding)
        finding_ids.append(finding.finding_id)
        stop_reason = "acceptance_evidence_obtained"
        if actions_used >= task.max_actions:
            stop_reason = "action_budget_exhausted_after_evidence"
        return TaskExecutionResult(
            task_id=task.task_id,
            status=ResearchTaskStatus.SUCCEEDED,
            actions_used=actions_used,
            observation_ids=tuple(observation_ids),
            evidence_ids=tuple(evidence_ids),
            finding_ids=tuple(finding_ids),
            stop_reason=stop_reason,
        )

    @staticmethod
    def _default_finding_builder(
        context: ApprovedResearchContext,
        task: ResearchTask,
        evidence: list[VerifiedEvidence],
        covers: list[str],
    ) -> Finding:
        # This deterministic fallback is deliberately conservative.  A future
        # model-backed Finding builder may rewrite the statement, but it must
        # retain these Evidence IDs and criterion mappings.
        statement = evidence[0].excerpt
        return Finding(
            finding_id=f"finding-{task.task_id}",
            research_id=context.job.research_id,
            task_id=task.task_id,
            statement=statement,
            evidence_ids=[item.evidence_id for item in evidence],
            covers=covers,
        )

    @staticmethod
    def _validate_context(context: ApprovedResearchContext) -> None:
        if context.job.research_id != context.plan.research_id:
            raise ValueError("approved context Job and Plan research_id mismatch")
        if context.job.research_id != context.manifest.research_id:
            raise ValueError("approved context Job and Manifest research_id mismatch")
        if context.job.research_id != context.approval.research_id:
            raise ValueError("approved context Job and Approval research_id mismatch")
        if context.approval.plan_version != context.plan.version:
            raise ValueError("approved context Approval and Plan version mismatch")
        if context.approval.manifest_hash != context.manifest.manifest_hash:
            raise ValueError("approved context Approval and Manifest hash mismatch")
        if context.plan.manifest_hash != context.manifest.manifest_hash:
            raise ValueError("approved context Plan and Manifest hash mismatch")
        if context.plan.status != ResearchPlanStatus.APPROVED:
            raise ValueError("Worker requires an approved Plan")
        if context.job.status not in {
            # Direct unit tests may start from READY; the production Dispatcher
            # uses RESEARCHING after its atomic claim.
            ResearchJobStatus.READY,
            ResearchJobStatus.RESEARCHING,
        }:
            raise ValueError("Worker requires an approved ready/researching Job")

    @staticmethod
    def _ordered_context_tasks(
        context: ApprovedResearchContext,
    ) -> list[ResearchTask]:
        from agent.schemas.research import ResearchPlanValidator

        ordered_plan_tasks = ResearchPlanValidator.topological_sort(context.plan)
        context_ids = {task.task_id for task in context.tasks}
        if context_ids != {task.task_id for task in ordered_plan_tasks}:
            raise ValueError("approved context tasks do not match the approved Plan")
        context_by_id = {task.task_id: task for task in context.tasks}
        plan_by_id = {task.task_id: task for task in ordered_plan_tasks}
        for task_id, task in context_by_id.items():
            if task.model_dump(exclude={"status"}) != plan_by_id[task_id].model_dump(
                exclude={"status"}
            ):
                raise ValueError("approved context Task differs from the approved Plan")
        # The dependency order comes from the approved Plan, while the task
        # payload itself comes from the Repository-backed context supplied by
        # the control plane.
        return [context_by_id[task.task_id] for task in ordered_plan_tasks]

    @staticmethod
    def _new_id(prefix: str, task_id: str, index: int) -> str:
        return f"{prefix}-{task_id}-{index + 1}-{uuid.uuid4().hex[:8]}"


__all__ = [
    "ConservativeCriterionMapper",
    "FindingBuilder",
    "InMemoryResearchLedger",
    "LocalResearchTools",
    "LocalResearchWorker",
    "OriginalRead",
    "ResearchLedger",
    "ResearchRunResult",
    "ResearchToolError",
    "SearchHit",
    "TaskExecutionResult",
]
