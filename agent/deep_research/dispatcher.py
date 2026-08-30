"""Small SQLite-backed dispatcher for Research Jobs.

There is no message broker in the Core Vertical Slice.  SQLite is the durable
queue, while the Repository remains the authoritative business state.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from agent.schemas.research import ResearchJobStatus

from .service import ApprovedResearchContext, ResearchControlPlane


class DurableDispatcher:
    """Perform one bounded scan of durable Jobs.

    The dispatcher is intentionally pull-based and has no background thread of
    its own.  Application wiring can call :meth:`scan_once` periodically.  A
    Worker is injected later; without one, approved Jobs stay ``ready`` rather
    than being falsely marked as running.
    """

    def __init__(
        self,
        control_plane: ResearchControlPlane,
        *,
        executor: Callable[[ApprovedResearchContext], None] | None = None,
        recovery_executor: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.control_plane = control_plane
        self.executor = executor
        self.recovery_executor = recovery_executor
        self.logger = logger or logging.getLogger("agent-layer.research.dispatcher")

    def scan_once(self) -> list[str]:
        """Claim and hand off ready Jobs, returning the IDs handed off."""

        dispatched: list[str] = []

        planning_jobs = self.control_plane.repository.list_jobs(
            [ResearchJobStatus.CREATED, ResearchJobStatus.PLANNING]
        )
        for job in planning_jobs:
            try:
                self.control_plane.resume_planning_job(job.research_id)
                dispatched.append(job.research_id)
            except Exception:
                self.logger.exception(
                    "research planning recovery failed for research_id=%s",
                    job.research_id,
                )

        ready_jobs = (
            self.control_plane.repository.list_jobs([ResearchJobStatus.READY])
            if self.executor is not None
            else []
        )
        for job in ready_jobs:
            try:
                context = self.control_plane.claim_for_execution(job.research_id)
                self.executor(context)
                dispatched.append(job.research_id)
            except Exception as exc:
                self._fail_running_job(job.research_id, exc)
                self.logger.exception(
                    "research dispatcher failed for research_id=%s",
                    job.research_id,
                )

        interrupted_jobs = (
            self.control_plane.repository.list_jobs(
                [ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING]
            )
            if self.recovery_executor is not None
            else []
        )
        for job in interrupted_jobs:
            if job.research_id in dispatched:
                continue
            try:
                self.recovery_executor(job.research_id)
                dispatched.append(job.research_id)
            except Exception as exc:
                self._fail_running_job(job.research_id, exc)
                self.logger.exception(
                    "research recovery failed for research_id=%s",
                    job.research_id,
                )
        return dispatched

    def _fail_running_job(self, research_id: str, exc: Exception) -> None:
        job = self.control_plane.repository.get_job(research_id)
        if job.status not in {
            ResearchJobStatus.RESEARCHING,
            ResearchJobStatus.SYNTHESIZING,
        }:
            return
        self.control_plane.repository.transition_job(
            research_id,
            expected_statuses=[job.status],
            status=ResearchJobStatus.FAILED,
            current_stage=job.current_stage,
            failure_stage=job.current_stage,
            error_code=exc.__class__.__name__,
        )

    def pending_job_ids(self) -> list[str]:
        """Expose durable queue visibility without claiming any Job."""

        jobs = self.control_plane.repository.list_jobs(
            [
                ResearchJobStatus.CREATED,
                ResearchJobStatus.PLANNING,
                ResearchJobStatus.READY,
                ResearchJobStatus.RESEARCHING,
                ResearchJobStatus.SYNTHESIZING,
            ]
        )
        return [job.research_id for job in jobs]


__all__ = ["DurableDispatcher"]
