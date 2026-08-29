"""LangGraph production skeleton over the authoritative Research Repository."""

from __future__ import annotations

from typing import Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agent.schemas.research import (
    ClaimDraft,
    ResearchJob,
    ResearchJobStatus,
    ResearchReport,
    VerificationResult,
    WorkflowCheckpoint,
)
from .repository import SQLiteResearchRepository
from .service import ResearchControlPlane
from .structural_verifier import StructuralVerifier


class RuntimeState(TypedDict, total=False):
    research_id: str
    current_stage: str
    current_task_id: str | None
    plan_version: int
    attempt: int
    entity_ids: list[str]


class IntelligencePipeline(Protocol):
    """Member A's components plug in without placing business objects in Graph state."""

    def execute_tasks(self, research_id: str) -> list[str]: ...
    def compute_coverage(self, research_id: str) -> list[str]: ...
    def generate_claims(self, research_id: str) -> list[str]: ...
    def semantic_verify(self, research_id: str, claim_ids: list[str]) -> list[VerificationResult]: ...
    def render_report(self, research_id: str) -> ResearchReport: ...


class ResearchGraphRuntime:
    def __init__(
        self,
        control_plane: ResearchControlPlane,
        pipeline: IntelligencePipeline,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        self.control_plane = control_plane
        self.repository: SQLiteResearchRepository = control_plane.repository
        self.pipeline = pipeline
        self.structural = StructuralVerifier(self.repository)
        self.graph = self._build(checkpointer)

    @staticmethod
    def config(research_id: str) -> dict:
        return {"configurable": {"thread_id": research_id}}

    def _stage(self, state: RuntimeState, stage: str, ids: list[str]) -> RuntimeState:
        checkpoint = WorkflowCheckpoint(
            research_id=state["research_id"], current_stage=stage,
            current_task_id=state.get("current_task_id"), plan_version=state.get("plan_version"),
            attempt=state.get("attempt", 0), entity_ids=ids,
        )
        self.repository.save_checkpoint(checkpoint)
        job = self.repository.get_job(state["research_id"])
        self.repository.update_job(ResearchJob.model_validate({**job.model_dump(), "current_stage": stage}))
        return {"current_stage": stage, "entity_ids": ids}

    def _prepare(self, state: RuntimeState) -> RuntimeState:
        self.control_plane.approved_context(state["research_id"])
        return self._stage(state, "execute_tasks", [])

    def _execute(self, state: RuntimeState) -> RuntimeState:
        return self._stage(state, "coverage", self.pipeline.execute_tasks(state["research_id"]))

    def _coverage(self, state: RuntimeState) -> RuntimeState:
        return self._stage(state, "generate_claims", self.pipeline.compute_coverage(state["research_id"]))

    def _claims(self, state: RuntimeState) -> RuntimeState:
        return self._stage(state, "structural_verification", self.pipeline.generate_claims(state["research_id"]))

    def _structural(self, state: RuntimeState) -> RuntimeState:
        manifest = self.repository.get_manifest(state["research_id"])
        claims = {item.claim_id: item for item in self.repository.list_claims(state["research_id"])}
        valid: list[str] = []
        for claim_id in state.get("entity_ids", []):
            claim: ClaimDraft | None = claims.get(claim_id)
            if claim is not None and self.structural.verify(claim, manifest).valid:
                valid.append(claim_id)
        return self._stage(state, "semantic_verification", valid)

    def _semantic(self, state: RuntimeState) -> RuntimeState:
        results = self.pipeline.semantic_verify(state["research_id"], state.get("entity_ids", []))
        for result in results:
            self.repository.save_verification(result, phase="semantic")
        job = self.repository.get_job(state["research_id"])
        transitioned = self.repository.transition_job(
            state["research_id"], expected_statuses=[ResearchJobStatus.RESEARCHING],
            status=ResearchJobStatus.SYNTHESIZING, current_stage="render_report",
        )
        if transitioned is None and job.status != ResearchJobStatus.SYNTHESIZING:
            raise RuntimeError("research_job_cannot_enter_synthesis")
        return self._stage(state, "render_report", [item.claim_id for item in results])

    def _render(self, state: RuntimeState) -> RuntimeState:
        report = self.pipeline.render_report(state["research_id"])
        self.repository.save_report(report)
        return self._stage(state, "finalize", [report.report_id])

    def _finalize(self, state: RuntimeState) -> RuntimeState:
        report = self.repository.get_report(state["research_id"])
        completed = self.repository.transition_job(
            state["research_id"], expected_statuses=[ResearchJobStatus.SYNTHESIZING],
            status=ResearchJobStatus.COMPLETED, current_stage="completed",
            result_status=report.result_status,
        )
        if completed is None:
            raise RuntimeError("research_job_cannot_complete")
        return self._stage(state, "completed", state.get("entity_ids", []))

    def _build(self, checkpointer: BaseCheckpointSaver):
        nodes = [
            ("prepare", self._prepare), ("execute_tasks", self._execute),
            ("coverage", self._coverage), ("generate_claims", self._claims),
            ("structural_verification", self._structural),
            ("semantic_verification", self._semantic),
            ("render_report", self._render), ("finalize", self._finalize),
        ]
        builder = StateGraph(RuntimeState)
        for name, callback in nodes:
            builder.add_node(name, callback)
        builder.add_edge(START, "prepare")
        for (source, _), (target, _) in zip(nodes, nodes[1:]):
            builder.add_edge(source, target)
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=checkpointer, name="deep-research-core")

    def run(self, research_id: str) -> dict:
        job = self.repository.get_job(research_id)
        if job.status != ResearchJobStatus.RESEARCHING or job.plan_version is None:
            raise RuntimeError("research_job_must_be_claimed_before_run")
        try:
            return self.graph.invoke(
                {"research_id": research_id, "current_stage": "prepare", "current_task_id": None,
                 "plan_version": job.plan_version, "attempt": 0, "entity_ids": []},
                self.config(research_id),
            )
        except Exception as exc:
            current = self.repository.get_job(research_id)
            if current.status in {ResearchJobStatus.RESEARCHING, ResearchJobStatus.SYNTHESIZING}:
                self.repository.transition_job(
                    research_id, expected_statuses=[current.status], status=ResearchJobStatus.FAILED,
                    current_stage=current.current_stage, failure_stage=current.current_stage,
                    error_code=exc.__class__.__name__,
                )
            raise

    def state(self, research_id: str):
        return self.graph.get_state(self.config(research_id))


__all__ = ["IntelligencePipeline", "ResearchGraphRuntime", "RuntimeState"]
