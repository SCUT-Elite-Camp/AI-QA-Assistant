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


STAGE_ORDER = ("created", "planning", "awaiting_approval", "ready", "parallel_exploration",
               "coordinator_synthesis", "review_report", "repair_report", "coordinator_check",
               "publish_report", "completed")
STAGE_LABELS = {
    "created": "Research created", "planning": "Creating research plan",
    "awaiting_approval": "Awaiting plan approval", "ready": "Research queued",
    "parallel_exploration": "Explorers researching in parallel",
    "coordinator_synthesis": "Coordinator assembling report", "review_report": "Reviewer checking evidence",
    "repair_report": "Independent agent correcting rejected draft", "coordinator_check": "Coordinator final check",
    "publish_report": "Releasing approved report", "completed": "Research complete",
}
STAGE_PROGRESS = {"created": 2, "planning": 10, "awaiting_approval": 15, "ready": 20,
    "parallel_exploration": 45, "coordinator_synthesis": 65, "review_report": 78,
    "repair_report": 82, "coordinator_check": 94, "publish_report": 98, "completed": 100}

_SAFE_ERROR_MESSAGES = {
    "ResearchReviewRejected": "Research could not produce an independently approved report. See exploration and review details; no final report was released.",
    "ResearchTeamProtocolError": "A research agent could not return a valid, evidence-bound result.",
    "ResearchTokenBudgetExceeded": "Research stopped at its approved model token budget. No unreviewed report was released.",
    "research_legacy_restart_required": "This saved plan uses the retired workflow. Start a new research job and approve its new plan.",
    "ResearchRecoveryError": "The saved execution cannot be resumed. Start a new research job and approve its plan.",
    "planning_failed": "Research planning failed. Check source availability and try again.",
    "research_checkpoint_missing": "No checkpoint is available to resume this research.",
    "research_checkpoint_unsafe": "Research stopped because the checkpoint could not be safely resumed.",
    "research_checkpoint_plan_mismatch": "The checkpoint does not match the current plan version.",
    "ManifestAccessError": "Sources have changed or are no longer accessible.",
    "LocalToolTimeout": "Reading research sources timed out. Please try again.",
}


class ResearchProgressService:
    """Aggregate authoritative entities and append-only events into one DTO."""

    def __init__(self, repository: SQLiteResearchRepository) -> None:
        self.repository = repository

    def team_summary(self, research_id):
        job = self.repository.get_job(research_id)
        if job.plan_version is None or self.repository.get_plan(research_id, job.plan_version).execution_mode != "coordinator":
            return None
        reviews = self.repository.list_team_entities("report_review", research_id)
        statuses = {r.draft_id: r.status for r in reviews}
        agents = [r.model_dump(mode="json") for r in self.repository.list_team_entities("agent_result", research_id)]
        completed = {a["agent_id"] for a in agents}
        for step in self.repository.list_team_entities("agent_step", research_id):
            if step.action == "started" and step.agent_id not in completed:
                agents.append({"agent_id": step.agent_id, "role": step.role, "task_id": step.task_id,
                    "status": "running" if job.status in {ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING} else "interrupted",
                    "missing": []})
        return {"agents": agents,
            "drafts": [{"draft_id": d.draft_id, "revision": d.revision, "report_hash": d.report_hash,
                        "author_agent_id": d.author_agent_id, "review_status": statuses.get(d.draft_id, "not_reviewed")}
                       for d in self.repository.list_team_entities("report_draft", research_id)],
            "reviews": [r.model_dump(mode="json") for r in reviews],
            "completion_tokens_used": self.repository.model_tokens_used(research_id)}

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
        metrics = self._metrics(job, events, evidence)
        if job.plan_version and self.repository.get_plan(research_id, job.plan_version).execution_mode == "coordinator":
            actions = sum(s.action in {"read", "search"} for s in self.repository.list_team_entities("agent_step", research_id))
            metrics = metrics.model_copy(update={"actions_used": actions, "tool_calls": actions})
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
            finding_count=self.repository.count_entities("finding", research_id),
            started_at=job.created_at,
            updated_at=job.updated_at,
            stages=self._stage_progress(job, current_stage, events),
            tasks=tasks,
            metrics=metrics,
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
        if candidate in STAGE_LABELS:
            return candidate
        for event in reversed(events):
            if event.stage in STAGE_LABELS:
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
        if current_stage == "parallel_exploration" and job.task_total:
            ratio = min(task_completed / job.task_total, 1.0)
            return round(20 + ratio * 28)
        return STAGE_PROGRESS[current_stage]

    def _stage_progress(self, job: ResearchJob, current_stage: str, events):
        order = STAGE_ORDER
        if not any(event.stage == "repair_report" for event in events):
            order = tuple(stage for stage in order if stage != "repair_report")
        started = {}
        completed = {}
        for event in events:
            if event.stage not in order:
                continue
            if event.event_type == ResearchEventType.STAGE_STARTED:
                started.setdefault(event.stage, event.created_at)
            elif event.event_type == ResearchEventType.STAGE_COMPLETED:
                completed.setdefault(event.stage, event.created_at)
        current_index = order.index(current_stage)
        output = []
        for index, key in enumerate(order):
            if job.status == ResearchJobStatus.COMPLETED:
                status = ResearchStageStatus.COMPLETED
            elif index == current_index and job.status == ResearchJobStatus.FAILED:
                status = ResearchStageStatus.FAILED
            elif index == current_index and job.status != ResearchJobStatus.CANCELLED:
                status = ResearchStageStatus.RUNNING
            elif key in completed or index < current_index:
                status = ResearchStageStatus.COMPLETED
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
                "Research failed. Please try again.",
            ),
        )


__all__ = [
    "ResearchProgressService",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STAGE_PROGRESS",
]
