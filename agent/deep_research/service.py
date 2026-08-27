"""Research Job control-plane service used by the API and future Worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid

from agent.schemas.research import (
    ResearchApproval,
    ResearchJob,
    ResearchJobStatus,
    ResearchPlan,
    ResearchPlanStatus,
    ResearchRequest,
    ResearchTask,
    SourceManifest,
)

from .manifest import LocalDocumentResolver, ManifestResolutionError, SourceResolver
from .planner import MockResearchPlanner, ResearchPlanner
from .repository import (
    ResearchConflictError,
    ResearchNotFoundError,
    SQLiteResearchRepository,
)


class ResearchControlPlaneError(RuntimeError):
    """Stable error exposed by the API control plane."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ApprovedResearchContext:
    """The only context a future Worker may use to start execution."""

    job: ResearchJob
    plan: ResearchPlan
    tasks: tuple[ResearchTask, ...]
    manifest: SourceManifest
    approval: ResearchApproval


class ResearchControlPlane:
    """Create and approve durable Local Research Jobs.

    Planning is intentionally synchronous in this Day 1–2 slice so the API
    can expose a simple control-plane contract.  The Job is inserted before
    source resolution and planning, so a later durable dispatcher can recover
    an interrupted ``created`` or ``planning`` Job.
    """

    def __init__(
        self,
        repository: SQLiteResearchRepository | None = None,
        *,
        source_resolver: SourceResolver | None = None,
        planner: ResearchPlanner | None = None,
        id_factory=None,
    ) -> None:
        if repository is None:
            project_root = Path(__file__).resolve().parents[2]
            repository = SQLiteResearchRepository(
                project_root / "data-persistence" / "data" / "research_jobs.db"
            )
        self.repository = repository
        self.source_resolver = source_resolver or LocalDocumentResolver()
        self.planner = planner or MockResearchPlanner()
        self.id_factory = id_factory or self._new_research_id

    def create_job(
        self,
        request: ResearchRequest,
        *,
        user_id: str = "local-user",
    ) -> ResearchJob:
        research_id = self.id_factory()
        job = ResearchJob(
            research_id=research_id,
            user_id=user_id,
            request=request,
        )
        self.repository.create_job(job)

        try:
            planning_job = self.repository.transition_job(
                research_id,
                expected_statuses=[ResearchJobStatus.CREATED],
                status=ResearchJobStatus.PLANNING,
            )
            if planning_job is None:
                raise ResearchControlPlaneError(
                    "research_job_state_conflict",
                    "new Research Job could not enter planning",
                )

            manifest = self.source_resolver.resolve(research_id, request.source_scope)
            if manifest.research_id != research_id:
                raise ResearchControlPlaneError(
                    "research_manifest_identity_mismatch",
                    "SourceManifest must belong to the newly created Research Job",
                )
            self.repository.save_manifest(manifest)
            planning_job = self.repository.transition_job(
                research_id,
                expected_statuses=[ResearchJobStatus.PLANNING],
                status=ResearchJobStatus.PLANNING,
                current_stage="planning",
                manifest_hash=manifest.manifest_hash,
            )
            if planning_job is None:
                raise ResearchControlPlaneError(
                    "research_job_state_conflict",
                    "Research Job changed while its SourceManifest was being saved",
                )

            plan = self.planner.create_plan(request, manifest, version=1)
            if plan.research_id != research_id:
                raise ResearchControlPlaneError(
                    "research_plan_identity_mismatch",
                    "ResearchPlan must belong to the newly created Research Job",
                )
            if plan.manifest_hash != manifest.manifest_hash:
                raise ResearchControlPlaneError(
                    "research_plan_manifest_mismatch",
                    "ResearchPlan must be bound to the frozen SourceManifest",
                )
            self.repository.save_plan(plan)
            awaiting_job = self.repository.transition_job(
                research_id,
                expected_statuses=[ResearchJobStatus.PLANNING],
                status=ResearchJobStatus.AWAITING_APPROVAL,
                current_stage="awaiting_approval",
                plan_version=plan.version,
                manifest_hash=manifest.manifest_hash,
                task_total=len(plan.tasks),
            )
            if awaiting_job is None:
                raise ResearchControlPlaneError(
                    "research_job_state_conflict",
                    "Research Job changed while its Plan was being saved",
                )
            return awaiting_job
        except (ManifestResolutionError, ResearchControlPlaneError):
            self._mark_failed_if_possible(research_id, "planning", "planning_failed")
            raise
        except Exception as exc:
            self._mark_failed_if_possible(research_id, "planning", "planning_failed")
            raise ResearchControlPlaneError(
                "planning_failed",
                str(exc) or exc.__class__.__name__,
            ) from exc

    def get_job(self, research_id: str) -> ResearchJob:
        return self.repository.get_job(research_id)

    def get_manifest(self, research_id: str) -> SourceManifest:
        return self.repository.get_manifest(research_id)

    def get_plan(self, research_id: str, version: int | None = None) -> ResearchPlan:
        return self.repository.get_plan(research_id, version)

    def approve_job(
        self,
        research_id: str,
        *,
        plan_version: int,
        manifest_hash: str,
        approved_by: str,
    ) -> ResearchJob:
        job = self.get_job(research_id)
        if job.status != ResearchJobStatus.AWAITING_APPROVAL:
            raise ResearchControlPlaneError(
                "research_approval_not_allowed",
                f"Job is '{job.status.value}', not awaiting approval",
            )
        if job.plan_version != plan_version:
            raise ResearchControlPlaneError(
                "research_plan_version_conflict",
                "approval must reference the current plan_version",
            )
        if job.manifest_hash != manifest_hash:
            raise ResearchControlPlaneError(
                "research_manifest_hash_conflict",
                "approval must reference the current manifest_hash",
            )

        manifest = self.get_manifest(research_id)
        if manifest.manifest_hash != manifest_hash:
            raise ResearchControlPlaneError(
                "research_manifest_hash_conflict",
                "SourceManifest has changed since the Job was created",
            )
        plan = self.get_plan(research_id, plan_version)
        if plan.manifest_hash != manifest_hash:
            raise ResearchControlPlaneError(
                "research_plan_manifest_mismatch",
                "Plan is not bound to the current SourceManifest",
            )
        if plan.status == ResearchPlanStatus.APPROVED:
            raise ResearchControlPlaneError(
                "research_already_approved",
                "this Plan has already been approved",
            )

        approval = ResearchApproval(
            research_id=research_id,
            plan_version=plan_version,
            manifest_hash=manifest_hash,
            approved_by=approved_by,
            approved_at=datetime.now(timezone.utc),
        )
        approved_plan = ResearchPlan.model_validate(
            {**plan.model_dump(), "status": ResearchPlanStatus.APPROVED}
        )
        ready_job = ResearchJob.model_validate(
            {
                **job.model_dump(),
                "status": ResearchJobStatus.READY,
                "current_stage": "ready",
                "plan_version": plan_version,
                "manifest_hash": manifest_hash,
            }
        )
        try:
            return self.repository.commit_approval(approval, approved_plan, ready_job)
        except ResearchConflictError as exc:
            raise ResearchControlPlaneError(
                "research_approval_state_conflict",
                str(exc),
            ) from exc

    def cancel_job(self, research_id: str) -> ResearchJob:
        cancelled = self.repository.transition_job(
            research_id,
            expected_statuses=[
                ResearchJobStatus.CREATED,
                ResearchJobStatus.PLANNING,
                ResearchJobStatus.AWAITING_APPROVAL,
                ResearchJobStatus.READY,
            ],
            status=ResearchJobStatus.CANCELLED,
            current_stage="cancelled",
        )
        if cancelled is None:
            job = self.get_job(research_id)
            raise ResearchControlPlaneError(
                "research_cancel_not_allowed",
                f"Job is '{job.status.value}' and cannot be cancelled now",
            )
        return cancelled

    def approved_context(self, research_id: str) -> ApprovedResearchContext:
        """Load and re-check every real entity required by a future Worker."""

        job = self.get_job(research_id)
        if job.plan_version is None or job.manifest_hash is None:
            raise ResearchControlPlaneError(
                "research_not_ready",
                "Job does not have a persisted Plan and SourceManifest",
            )
        plan = self.get_plan(research_id, job.plan_version)
        manifest = self.get_manifest(research_id)
        approval = self.repository.get_approval(research_id, job.plan_version)
        if plan.status != ResearchPlanStatus.APPROVED:
            raise ResearchControlPlaneError(
                "research_plan_not_approved",
                "ResearchPlan is not in approved state",
            )
        if approval.plan_version != plan.version:
            raise ResearchControlPlaneError(
                "research_approval_version_conflict",
                "Approval does not match the current Plan",
            )
        if approval.manifest_hash != manifest.manifest_hash:
            raise ResearchControlPlaneError(
                "research_approval_manifest_conflict",
                "Approval does not match the frozen SourceManifest",
            )
        if plan.manifest_hash != manifest.manifest_hash:
            raise ResearchControlPlaneError(
                "research_plan_manifest_mismatch",
                "Plan and SourceManifest are not bound to the same hash",
            )
        if job.manifest_hash != manifest.manifest_hash:
            raise ResearchControlPlaneError(
                "research_job_manifest_mismatch",
                "Job and SourceManifest are not bound to the same hash",
            )
        if job.status not in {
            ResearchJobStatus.READY,
            ResearchJobStatus.RESEARCHING,
            ResearchJobStatus.SYNTHESIZING,
        }:
            raise ResearchControlPlaneError(
                "research_execution_not_allowed",
                f"Job is '{job.status.value}' and has not been approved for execution",
            )
        tasks = tuple(self.repository.get_tasks(research_id, plan.version))
        return ApprovedResearchContext(
            job=job,
            plan=plan,
            tasks=tasks,
            manifest=manifest,
            approval=approval,
        )

    def claim_for_execution(self, research_id: str) -> ApprovedResearchContext:
        """Atomically move an approved Job to researching for a future Worker."""

        context = self.approved_context(research_id)
        claimed = self.repository.transition_job(
            research_id,
            expected_statuses=[ResearchJobStatus.READY],
            status=ResearchJobStatus.RESEARCHING,
            current_stage="researching",
        )
        if claimed is None:
            raise ResearchControlPlaneError(
                "research_execution_claim_conflict",
                "another dispatcher already claimed this Job",
            )
        return ApprovedResearchContext(
            job=claimed,
            plan=context.plan,
            tasks=context.tasks,
            manifest=context.manifest,
            approval=context.approval,
        )

    @staticmethod
    def _new_research_id() -> str:
        return f"research-{uuid.uuid4().hex}"

    def _mark_failed_if_possible(
        self,
        research_id: str,
        failure_stage: str,
        error_code: str,
    ) -> None:
        try:
            job = self.repository.get_job(research_id)
            failed = ResearchJob.model_validate(
                {
                    **job.model_dump(),
                    "status": ResearchJobStatus.FAILED,
                    "current_stage": failure_stage,
                    "failure_stage": failure_stage,
                    "error_code": error_code,
                }
            )
            self.repository.update_job(failed)
        except Exception:
            # The original error is more useful to the API caller.  A later
            # dispatcher/reconciliation pass can inspect the durable record.
            return


__all__ = [
    "ApprovedResearchContext",
    "ResearchControlPlane",
    "ResearchControlPlaneError",
]
