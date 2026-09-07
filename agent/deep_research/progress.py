"""Persistent Research progress read model for the Web client."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from agent.schemas.research import (
    ResearchEventsResponse,
    ResearchEventType,
    ResearchJob,
    ResearchJobStatus,
    ResearchProgress,
    ResearchProgressError,
    ResearchRunMetrics,
    ResearchStageProgress,
    ResearchStageStatus,
    ResearchTaskProgress,
    ResearchTaskStatus,
)

from .repository import ResearchNotFoundError, SQLiteResearchRepository


STAGE_ORDER = (
    "created",
    "planning",
    "awaiting_approval",
    "ready",
    "execute_tasks",
    "coverage",
    "generate_claims",
    "structural_verification",
    "semantic_verification",
    "render_report",
    "finalize",
    "completed",
)

STAGE_LABELS = {
    "created": "已创建研究任务",
    "planning": "正在生成研究计划",
    "awaiting_approval": "等待确认研究计划",
    "ready": "研究任务等待执行",
    "execute_tasks": "正在执行研究任务",
    "coverage": "正在检查资料覆盖度",
    "generate_claims": "正在整理研究结论",
    "structural_verification": "正在检查引用完整性",
    "semantic_verification": "正在验证研究结论",
    "render_report": "正在生成研究报告",
    "finalize": "正在完成研究任务",
    "completed": "研究已完成",
}

STAGE_PROGRESS = {
    "created": 2,
    "planning": 10,
    "awaiting_approval": 15,
    "ready": 20,
    "execute_tasks": 48,
    "coverage": 58,
    "generate_claims": 68,
    "structural_verification": 76,
    "semantic_verification": 86,
    "render_report": 95,
    "finalize": 98,
    "completed": 100,
}

_SAFE_ERROR_MESSAGES = {
    "planning_failed": "研究计划生成失败，请检查所选资料后重试。",
    "research_checkpoint_missing": "研究任务缺少可恢复的执行位置。",
    "research_checkpoint_unsafe": "研究任务的恢复位置不安全，已停止执行。",
    "research_checkpoint_plan_mismatch": "研究计划版本与恢复位置不一致。",
    "ManifestAccessError": "所选资料已变化或当前无法访问。",
    "LocalToolTimeout": "读取研究资料超时，请稍后重试。",
}


class ResearchProgressService:
    """Aggregate authoritative entities and append-only events into one DTO."""

    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository

    def get_progress(self, research_id: str) -> ResearchProgress:
        job = self.repository.get_job(research_id)
        events = self.repository.list_events(research_id, limit=100)
        tasks = self._task_progress(job, events)
        completed = max(
            job.task_completed,
            sum(item.status == ResearchTaskStatus.SUCCEEDED for item in tasks),
        )
        completed = min(completed, job.task_total)
        current_stage = self._current_stage(job, events)
        evidence = self.repository.list_evidence(research_id)
        return ResearchProgress(
            research_id=research_id,
            status=job.status,
            result_status=job.result_status,
            current_stage=current_stage,
            progress_percent=self._progress_percent(job, current_stage, completed),
            task_total=job.task_total,
            task_completed=completed,
            evidence_count=len(evidence),
            claim_count=self.repository.count_entities("claim", research_id),
            started_at=job.created_at,
            updated_at=job.updated_at,
            stages=self._stage_progress(job, current_stage, events),
            tasks=tasks,
            metrics=self._metrics(job, events, evidence),
            error=self._safe_error(job),
        )

    @staticmethod
    def _metrics(job: ResearchJob, events, evidence) -> ResearchRunMetrics:
        terminal = job.status in {
            ResearchJobStatus.COMPLETED,
            ResearchJobStatus.FAILED,
            ResearchJobStatus.CANCELLED,
        }
        end = job.updated_at if terminal else datetime.now(timezone.utc)
        execution_start = next(
            (
                event.created_at
                for event in events
                if event.event_type == ResearchEventType.STAGE_STARTED
                and event.stage == "ready"
            ),
            job.created_at,
        )
        actions = sum(
            int(event.payload.get("actions_used", 0))
            for event in events
            if event.event_type
            in {
                ResearchEventType.TASK_COMPLETED,
                ResearchEventType.TASK_FAILED,
                ResearchEventType.TASK_BLOCKED,
            }
        )
        recoveries = sum(
            event.event_type == ResearchEventType.JOB_RECOVERED for event in events
        )
        return ResearchRunMetrics(
            elapsed_ms=max(0, round((end - execution_start).total_seconds() * 1000)),
            actions_used=actions,
            tool_calls=actions,
            documents_read=len({item.doc_id for item in evidence}),
            evidence_accepted=len(evidence),
            evidence_rejected=0,
            retry_count=recoveries,
            recovery_count=recoveries,
        )

    def get_events(
        self,
        research_id: str,
        *,
        after_event_id: int = 0,
        limit: int = 50,
    ) -> ResearchEventsResponse:
        self.repository.get_job(research_id)
        events = self.repository.list_events(
            research_id,
            after_event_id=after_event_id,
            limit=limit,
        )
        return ResearchEventsResponse(
            research_id=research_id,
            events=events,
            next_after_event_id=(events[-1].event_id if events else after_event_id),
        )

    def _task_progress(self, job: ResearchJob, events) -> list[ResearchTaskProgress]:
        if job.plan_version is None:
            return []
        try:
            tasks = self.repository.get_tasks(job.research_id, job.plan_version)
        except ResearchNotFoundError:
            return []
        latest = {}
        for event in events:
            if event.task_id and event.event_type in {
                ResearchEventType.TASK_STARTED,
                ResearchEventType.TASK_COMPLETED,
                ResearchEventType.TASK_FAILED,
                ResearchEventType.TASK_BLOCKED,
            }:
                latest[event.task_id] = event
        output: list[ResearchTaskProgress] = []
        for task in tasks:
            status = task.status
            event = latest.get(task.task_id)
            if event is not None:
                if event.event_type == ResearchEventType.TASK_STARTED:
                    status = ResearchTaskStatus.RUNNING
                elif event.event_type == ResearchEventType.TASK_COMPLETED:
                    status = ResearchTaskStatus.SUCCEEDED
                elif event.event_type == ResearchEventType.TASK_FAILED:
                    status = ResearchTaskStatus.FAILED
                elif event.event_type == ResearchEventType.TASK_BLOCKED:
                    status = ResearchTaskStatus.BLOCKED
            output.append(
                ResearchTaskProgress(
                    task_id=task.task_id,
                    question=task.question,
                    status=status,
                    evidence_count=self.repository.count_entities(
                        "evidence", job.research_id, task.task_id
                    ),
                )
            )
        return output

    @staticmethod
    def _current_stage(job: ResearchJob, events) -> str:
        if job.status == ResearchJobStatus.COMPLETED:
            return "completed"
        candidate = job.failure_stage or job.current_stage
        if candidate in STAGE_ORDER:
            return candidate
        for event in reversed(events):
            if event.stage in STAGE_ORDER:
                return event.stage
        if job.status.value in STAGE_ORDER:
            return job.status.value
        return "created"

    @staticmethod
    def _progress_percent(
        job: ResearchJob,
        current_stage: str,
        task_completed: int,
    ) -> int:
        if job.status == ResearchJobStatus.COMPLETED:
            return 100
        if current_stage == "execute_tasks" and job.task_total:
            ratio = min(task_completed / job.task_total, 1.0)
            return round(20 + ratio * 28)
        return STAGE_PROGRESS[current_stage]

    @staticmethod
    def _stage_progress(job: ResearchJob, current_stage: str, events):
        started = {}
        completed = {}
        for event in events:
            if event.stage not in STAGE_ORDER:
                continue
            if event.event_type == ResearchEventType.STAGE_STARTED:
                started.setdefault(event.stage, event.created_at)
            elif event.event_type == ResearchEventType.STAGE_COMPLETED:
                completed.setdefault(event.stage, event.created_at)
        current_index = STAGE_ORDER.index(current_stage)
        output = []
        for index, key in enumerate(STAGE_ORDER):
            if job.status == ResearchJobStatus.COMPLETED or index < current_index:
                status = ResearchStageStatus.COMPLETED
            elif index == current_index and job.status == ResearchJobStatus.FAILED:
                status = ResearchStageStatus.FAILED
            elif index == current_index and job.status != ResearchJobStatus.CANCELLED:
                status = ResearchStageStatus.RUNNING
            else:
                status = ResearchStageStatus.PENDING
            output.append(
                ResearchStageProgress(
                    key=key,
                    label=STAGE_LABELS[key],
                    status=status,
                    started_at=started.get(key),
                    completed_at=completed.get(key),
                )
            )
        return output

    @staticmethod
    def _safe_error(job: ResearchJob) -> ResearchProgressError | None:
        if job.status != ResearchJobStatus.FAILED:
            return None
        raw_code = job.error_code or "research_failed"
        code = (
            raw_code
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", raw_code)
            else "research_failed"
        )
        return ResearchProgressError(
            stage=job.failure_stage or job.current_stage,
            code=code,
            message=_SAFE_ERROR_MESSAGES.get(
                code,
                "研究任务执行失败，请稍后重试。",
            ),
        )


__all__ = [
    "ResearchProgressService",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STAGE_PROGRESS",
]
