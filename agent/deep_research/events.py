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
            "已创建研究任务",
            stage="created",
        )
        self.stage_started(research_id, "created")
        return event

    def plan_approved(self, research_id: str, plan_version: int) -> ResearchEvent:
        return self._append(
            research_id,
            f"plan:{plan_version}:approved",
            ResearchEventType.PLAN_APPROVED,
            "研究计划已确认",
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
            f"研究计划已更新为 v{to_version}，需要重新确认",
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
            f"已从检查点恢复，继续执行{STAGE_LABELS.get(stage, '研究任务')}",
            stage=stage,
            payload={"attempt": attempt, "resumed_stage": stage},
        )

    def stage_started(self, research_id: str, stage: str) -> ResearchEvent:
        return self._append(
            research_id,
            f"stage:{stage}:started",
            ResearchEventType.STAGE_STARTED,
            STAGE_LABELS.get(stage, "研究阶段已开始"),
            stage=stage,
        )

    def stage_completed(self, research_id: str, stage: str) -> ResearchEvent:
        label = STAGE_LABELS.get(stage, "研究阶段")
        return self._append(
            research_id,
            f"stage:{stage}:completed",
            ResearchEventType.STAGE_COMPLETED,
            f"{label}完成",
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
            "开始执行研究任务",
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
            message = "研究任务已完成"
        elif status == ResearchTaskStatus.BLOCKED:
            event_type = ResearchEventType.TASK_BLOCKED
            suffix = "blocked"
            message = "研究任务因依赖未完成而跳过"
        else:
            event_type = ResearchEventType.TASK_FAILED
            suffix = "failed"
            message = "研究任务未取得可验证证据"
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
            "研究报告已生成",
            stage="render_report",
            payload={"report_id": report_id},
        )

    def job_completed(self, research_id: str, result_status: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:completed",
            ResearchEventType.JOB_COMPLETED,
            "研究已完成",
            stage="completed",
            payload={"result_status": result_status},
        )

    def job_failed(self, research_id: str, stage: str, code: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:failed",
            ResearchEventType.JOB_FAILED,
            "研究任务执行失败",
            stage=stage,
            payload={"error_code": code},
        )

    def job_cancelled(self, research_id: str, stage: str) -> ResearchEvent:
        return self._append(
            research_id,
            "job:cancelled",
            ResearchEventType.JOB_CANCELLED,
            "研究任务已取消",
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
