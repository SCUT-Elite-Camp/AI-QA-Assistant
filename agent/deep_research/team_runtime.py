"""Durable graph: parallel exploration -> draft -> review/repair -> release."""
from langgraph.graph import START, END, StateGraph

from agent.schemas.research import ResearchJobStatus, ResearchJob
from .access import model_access_scope
from .model_budget import completion_budget_scope
from .team_contracts import research_error_code
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypedDict
from langgraph.checkpoint.base import BaseCheckpointSaver
from agent.schemas.research import WorkflowCheckpoint
from .events import ResearchEventRecorder
from .repository import SQLiteResearchRepository
from .service import ResearchControlPlane


class ResearchRecoveryError(RuntimeError):
    pass


class ResearchRuntimeTimeout(RuntimeError):
    pass


class RuntimeState(TypedDict, total=False):
    research_id: str
    current_stage: str
    current_task_id: str | None
    plan_version: int
    attempt: int
    entity_ids: list[str]

from .team import ResearchReviewRejected


class ResearchTeamRuntime:
    recovery_stages = {"parallel_exploration", "coordinator_synthesis", "review_report",
                       "repair_report", "coordinator_check", "publish_report"}

    def _build(self, checkpointer):
        builder = StateGraph(RuntimeState)
        for name, node in [("prepare", self._team_prepare), ("explore", self._team_explore),
                           ("compose", self._team_compose), ("review", self._team_review),
                           ("repair", self._team_repair), ("check", self._team_check), ("publish", self._team_publish)]:
            builder.add_node(name, node)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "explore")
        builder.add_edge("explore", "compose")
        builder.add_edge("compose", "review")
        builder.add_conditional_edges("review", self._review_route, {"check": "check", "repair": "repair"})
        builder.add_edge("repair", "review")
        builder.add_edge("check", "publish")
        builder.add_edge("publish", END)
        return builder.compile(checkpointer=checkpointer, name="research-coordinator-team")

    def _assert_runtime_budget(self, research_id):
        self._check_budget(research_id)
        if self.repository.get_job(research_id).status not in {ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING}:
            raise ResearchReviewRejected("research_team_not_running")

    def _invoke_with_failure_policy(self, research_id, *, attempt):
        job = self.repository.get_job(research_id)
        plan = self.repository.get_plan(research_id, job.plan_version)
        with completion_budget_scope(plan.budget.max_tokens, spent=self.repository.model_tokens_used(research_id),
                reserve_hook=lambda tokens: self.repository.reserve_model_tokens(research_id, tokens, plan.budget.max_tokens),
                settle_hook=self.repository.settle_model_tokens), model_access_scope(lambda: self._assert_runtime_budget(research_id)):
            return self._invoke_graph(research_id, attempt=attempt)

    def _team_prepare(self, state):
        self.control_plane.approved_context(state["research_id"])
        return self._stage(state, "parallel_exploration", [])

    def _team_explore(self, state):
        ids = self.coordinator.explore(state["research_id"])
        self.repository.transition_job(state["research_id"], expected_statuses=[ResearchJobStatus.RESEARCHING],
                                       status=ResearchJobStatus.SYNTHESIZING, current_stage="coordinator_synthesis")
        return self._stage(state, "coordinator_synthesis", ids)

    def _team_compose(self, state):
        draft = self.coordinator.compose(state["research_id"])
        return self._stage(state, "review_report", [draft.draft_id])

    def _team_review(self, state):
        review = self.coordinator.review(state["research_id"])
        stage = "coordinator_check" if review.status == "passed" else "repair_report"
        return self._stage(state, stage, [review.review_id])

    def _review_route(self, state):
        return "check" if state["current_stage"] == "coordinator_check" else "repair"

    def _team_repair(self, state):
        draft = self.coordinator.repair(state["research_id"])
        return self._stage(state, "review_report", [draft.draft_id])

    def _team_check(self, state):
        self.coordinator.final_check(state["research_id"])
        return self._stage(state, "publish_report", [])

    def _team_publish(self, state):
        rid = state["research_id"]
        report = self.coordinator.final_check(rid)
        self._assert_runtime_budget(rid)
        self.repository.save_report(report)
        self.events.report_ready(rid, report.report_id)
        if self.stage_hook:
            self.stage_hook(rid, "report_persisted")
        # Finalize cannot call _stage after COMPLETED: its model/tool guard rejects terminal jobs.
        self.events.stage_completed(rid, "publish_report")
        completed = self.repository.transition_job(rid, expected_statuses=[ResearchJobStatus.SYNTHESIZING],
            status=ResearchJobStatus.COMPLETED, current_stage="completed", result_status=report.result_status)
        if completed is None:
            raise ResearchReviewRejected("research_release_state_changed")
        self.events.stage_started(rid, "completed")
        self.events.stage_completed(rid, "completed")
        self.events.job_completed(rid, report.result_status.value)
        return {"current_stage": "completed", "entity_ids": [report.report_id]}


    def __init__(
        self,
        control_plane: ResearchControlPlane,
        coordinator,
        checkpointer: BaseCheckpointSaver,
        *,
        stage_hook: Callable[[str, str], None] | None = None,
        event_recorder: ResearchEventRecorder | None = None,
    ) -> None:
        self.control_plane = control_plane
        self.repository: SQLiteResearchRepository = control_plane.repository
        self.coordinator = coordinator
        self.stage_hook = stage_hook
        self.events = event_recorder or control_plane.events
        self.graph = self._build(checkpointer)

    @staticmethod
    def config(research_id: str) -> dict:
        return {"configurable": {"thread_id": research_id}}

    def _stage(self, state: RuntimeState, stage: str, ids: list[str]) -> RuntimeState:
        research_id = state["research_id"]
        self._assert_runtime_budget(research_id)
        previous_stage = state.get("current_stage")
        checkpoint = WorkflowCheckpoint(
            research_id=research_id, current_stage=stage,
            current_task_id=state.get("current_task_id"), plan_version=state.get("plan_version"),
            attempt=state.get("attempt", 0), entity_ids=ids,
        )
        self.repository.save_checkpoint(checkpoint)
        job = self.repository.get_job(research_id)
        updated = self.repository.transition_job(research_id,
            expected_statuses=[ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING],
            status=job.status, current_stage=stage)
        if updated is None:
            raise RuntimeError("research_stage_state_changed")
        if previous_stage not in {None, "prepare", stage}:
            self.events.stage_completed(research_id, previous_stage)
        self.events.stage_started(research_id, stage)
        if self.stage_hook is not None:
            self.stage_hook(research_id, f"checkpoint:{stage}")
        return {"current_stage": stage, "entity_ids": ids}

    def _check_budget(self, research_id: str) -> None:
        job = self.repository.get_job(research_id)
        self.control_plane.authorize_job(job, self.control_plane.get_manifest(research_id))
        if job.plan_version is None:
            return
        plan = self.repository.get_plan(research_id, job.plan_version)
        if plan.execution_mode != "coordinator":
            raise ResearchRecoveryError("research_legacy_restart_required")
        elapsed = (datetime.now(timezone.utc) - (getattr(job, "execution_started_at", None) or job.updated_at)).total_seconds()
        if elapsed > plan.budget.max_runtime_seconds:
            raise ResearchRuntimeTimeout("research_runtime_budget_exceeded")

    def run(self, research_id: str) -> dict:
        job = self.repository.get_job(research_id)
        if job.status != ResearchJobStatus.RESEARCHING or job.plan_version is None:
            raise RuntimeError("research_job_must_be_claimed_before_run")
        return self._invoke_with_failure_policy(research_id, attempt=0)

    def resume(self, research_id: str) -> dict:
        """Replay an interrupted Job from durable, idempotent stage data."""

        job = self.repository.get_job(research_id)
        if job.status not in {
            ResearchJobStatus.RESEARCHING,
            ResearchJobStatus.SYNTHESIZING,
        }:
            raise ResearchRecoveryError("research_job_is_not_interrupted")
        try:
            checkpoint = self.repository.get_checkpoint(research_id)
        except Exception as exc:
            self._fail_recovery(job, "research_checkpoint_missing")
            raise ResearchRecoveryError("research_checkpoint_missing") from exc
        if checkpoint.current_stage not in self.recovery_stages:
            self._fail_recovery(job, "research_checkpoint_unsafe")
            raise ResearchRecoveryError("research_checkpoint_unsafe")
        if checkpoint.plan_version != job.plan_version:
            self._fail_recovery(job, "research_checkpoint_plan_mismatch")
            raise ResearchRecoveryError("research_checkpoint_plan_mismatch")
        next_attempt = checkpoint.attempt + 1
        self.events.job_recovered(
            research_id,
            attempt=next_attempt,
            stage=checkpoint.current_stage,
        )
        return self._invoke_with_failure_policy(
            research_id,
            attempt=next_attempt,
        )

    def _invoke_graph(self, research_id: str, *, attempt: int) -> dict:
        job = self.repository.get_job(research_id)
        try:
            return self.graph.invoke(
                {"research_id": research_id, "current_stage": "prepare", "current_task_id": None,
                 "plan_version": job.plan_version, "attempt": attempt, "entity_ids": []},
                self.config(research_id),
            )
        except Exception as exc:
            current = self.repository.get_job(research_id)
            code = research_error_code(exc)
            if current.status in {ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING}:
                failed = self.repository.transition_job(
                    research_id, expected_statuses=[current.status], status=ResearchJobStatus.FAILED,
                    current_stage=current.current_stage, failure_stage=current.current_stage,
                    error_code=code,
                )
                if failed is not None:
                    self.events.job_failed(
                        research_id,
                        current.current_stage,
                        code,
                    )
            raise

    def _fail_recovery(self, job: ResearchJob, error_code: str) -> None:
        failed = self.repository.transition_job(
            job.research_id,
            expected_statuses=[job.status],
            status=ResearchJobStatus.FAILED,
            current_stage=job.current_stage,
            failure_stage=job.current_stage,
            error_code=error_code,
        )
        if failed is not None:
            self.events.job_failed(job.research_id, job.current_stage, error_code)

    def state(self, research_id: str):
        return self.graph.get_state(self.config(research_id))
