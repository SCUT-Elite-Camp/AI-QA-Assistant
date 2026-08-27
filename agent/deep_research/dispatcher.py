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
        logger: logging.Logger | None = None,
    ) -> None:
        self.control_plane = control_plane
        self.executor = executor
        self.logger = logger or logging.getLogger("agent-layer.research.dispatcher")

    def scan_once(self) -> list[str]:
        """Claim and hand off ready Jobs, returning the IDs handed off."""

        if self.executor is None:
            return []

        dispatched: list[str] = []
        jobs = self.control_plane.repository.list_jobs([ResearchJobStatus.READY])
        for job in jobs:
            try:
                context = self.control_plane.claim_for_execution(job.research_id)
                self.executor(context)
                dispatched.append(job.research_id)
            except Exception:
                self.logger.exception(
                    "research dispatcher failed for research_id=%s",
                    job.research_id,
                )
        return dispatched

    def pending_job_ids(self) -> list[str]:
        """Expose durable queue visibility without claiming any Job."""

        jobs = self.control_plane.repository.list_jobs(
            [ResearchJobStatus.CREATED, ResearchJobStatus.READY]
        )
        return [job.research_id for job in jobs]


__all__ = ["DurableDispatcher"]
