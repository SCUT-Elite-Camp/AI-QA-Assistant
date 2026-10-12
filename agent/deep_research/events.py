"""Idempotent, user-safe Research event recording."""

from __future__ import annotations

from agent.schemas.research import (
    ResearchEvent,
    ResearchEventType,
    ResearchTaskStatus,
)

from .progress import STAGE_LABELS
from .repository import SQLiteResearchRepository


class ResearchEventRecorder:
    """Write stable events that remain safe when workflow stages are replayed."""

    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository

    def job_created(self, research_id: str) -> ResearchEvent:
        event = self._append(
            research_id,
            "job:created",
            ResearchEventType.JOB_CREATED,
            "Research created",
            stage="created",
        )
        self.stage_started(research_id, "created")
        return event

    def plan_approved(self, research_id: str, plan_version: int) -> ResearchEvent:
        return self._append(
            research_id,
            f"plan:{plan_version}:approved",
            ResearchEventType.PLAN_APPROVED,
            "Research plan approved",
            stage="awaiting_approval",
            payload={"plan_version": plan_version},
        )

    def plan_revised(
        self,
        research_id: str,
        *,
        from_version: int,
        to_version: int,
        revised_by: str,
        revision_note: str = "",
    ) -> ResearchEvent:
        return self._append(
            research_id,
            f"plan:{to_version}:revised",
            ResearchEventType.PLAN_REVISED,
            f"Plan updated to v{to_version}. Approval is required.",
            stage="awaiting_approval",
            payload={
                "from_version": from_version,
                "to_version": to_version,
                "revised_by": revised_by,
                "revision_note": revision_note,
            },
        )

    def job_recovered(
        self,
        research_id: str,
        *,
        attempt: int,
        stage: str,
    ) -> ResearchEvent:
        return self._append(
            research_id,
            f"recovery:{attempt}",
            ResearchEventType.JOB_RECOVERED,
            f"Restored from checkpoint. Resuming: {STAGE_LABELS.get(stage, 'Research')}",
            stage=stage,
            payload={"attempt": attempt, "resumed_stage": stage},
        )

    def stage_started(self, research_id: str, stage: str) -> ResearchEvent:
        return self._append(
            research_id,
            f"stage:{stage}:started",
            ResearchEventType.STAGE_STARTED,
            STAGE_LABELS.get(stage, "Research stage started"),
            stage=stage,
        )

    def stage_completed(self, research_id: str, stage: str) -> ResearchEvent:
        label = STAGE_LABELS.get(stage, "Research stage")
        return self._append(
            research_id,
            f"stage:{stage}:completed",
            ResearchEventType.STAGE_COMPLETED,
            f"{label}: completed",
            stage=stage,
        )

    def task_started(
        self,
        research_id: str,
        task_id: str,
    ) -> ResearchEvent:
        return self._append(
            research_id,
            f"task:{task_id}:started",
            ResearchEventType.TASK_STARTED,
            "Research task started",
            stage="execute_tasks",
            task_id=task_id,
        )

    def task_finished(
        self,
        research_id: str,
        task_id: str,
        *,
        status: ResearchTaskStatus,
        evidence_count: int,
        actions_used: int,
    ) -> ResearchEvent:
        if status == ResearchTaskStatus.SUCCEEDED:
            event_type = ResearchEventType.TASK_COMPLETED
            suffix = "completed"
            message = "Research task completed"
        elif status == ResearchTaskStatus.BLOCKED:
            event_type = ResearchEventType.TASK_BLOCKED
            suffix = "blocked"
            message = "Research task skipped because a dependency did not complete"
        else:
            event_type = ResearchEventType.TASK_FAILED
            suffix = "failed"
            message = "Research task did not obtain verifiable evidence"
        return self._append(
            research_id,
            f"task:{task_id}:{suffix}",
            event_type,
            message,
            stage="execute_tasks",
            task_id=task_id,
            payload={
                "status": status.value,
                "evidence_count": evidence_count,
                "actions_used": actions_used,
            },
        )

    def report_ready(self, research_id: str, report_id: str) -> ResearchEvent:
        return self._append(
            research_id,
            f"report:{report_id}:ready",
            ResearchEventType.REPORT_READY,
            "Research report ready",
            stage="render_report",
            payload={"report_id": report_id},
        )

    def job_completed(self, research_id: str, result_status: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:completed",
            ResearchEventType.JOB_COMPLETED,
            "Research complete",
            stage="completed",
            payload={"result_status": result_status},
        )

    def job_failed(self, research_id: str, stage: str, code: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:failed",
            ResearchEventType.JOB_FAILED,
            "Research failed",
            stage=stage,
            payload={"error_code": code},
        )

    def job_cancelled(self, research_id: str, stage: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:cancelled",
            ResearchEventType.JOB_CANCELLED,
            "Research cancelled",
            stage=stage,
        )

    def _append(
        self,
        research_id: str,
        key_suffix: str,
        event_type: ResearchEventType,
        message: str,
        *,
        stage: str | None = None,
        task_id: str | None = None,
        payload: dict[str, str | int | float | bool | None] | None = None,
    ) -> ResearchEvent:
        return self.repository.append_event(
            research_id=research_id,
            event_key=f"{research_id}:{key_suffix}",
            event_type=event_type,
            stage=stage,
            task_id=task_id,
            message=message,
            payload=payload,
        )


__all__ = ["ResearchEventRecorder"]
