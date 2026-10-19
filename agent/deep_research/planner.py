"""Minimal Planner interface for the Local Deep Research control plane."""

from __future__ import annotations

import json
from agent.config.settings import settings
from agent.llm.provider_options import apply_provider_options
from typing import Protocol
from .model_budget import completion_budget_scope, post_completion, with_completion_budget
from .team_contracts import unwrap_json_object

from agent.schemas.research import (
    AcceptanceCriterion,
    ResearchBudget,
    ResearchPlan,
    ResearchPlanStatus,
    ResearchPlanValidator,
    ResearchRequest,
    ResearchTask,
    SourceManifest,
)


class ResearchPlanner(Protocol):
    def create_plan(
        self,
        request: ResearchRequest,
        manifest: SourceManifest,
        *,
        version: int = 1,
    ) -> ResearchPlan:
        """Create and validate a bounded plan for one frozen manifest."""


class PlannerError(ValueError):
    """Raised when a planner cannot produce a valid bounded plan."""






class ModelResearchPlanner:
    """Generate the human-approved plan for the coordinator harness."""

    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.RESEARCH_MODEL_TIMEOUT_SECONDS

    def create_plan(self, request: ResearchRequest, manifest: SourceManifest, *, version: int = 1) -> ResearchPlan:
        with completion_budget_scope():
            return self._create_plan(request, manifest, version=version)

    def _create_plan(self, request: ResearchRequest, manifest: SourceManifest, *, version: int = 1) -> ResearchPlan:
        if not self.api_key:
            raise PlannerError("research_planner_model_required")
        try:
            tasks = self._team_tasks(request, manifest)
            plan = ResearchPlan(
                schema_version="research.v2",
                research_id=manifest.research_id,
                version=version,
                objective=request.query,
                out_of_scope=["Sources outside SourceManifest", "Speculation not verifiable in original sources"],
                source_scope=request.source_scope,
                report_spec=request.report_spec,
                manifest_hash=manifest.manifest_hash,
                tasks=tasks,
                budget=ResearchBudget(
                    max_tasks=6,
                    max_actions=64,
                    max_tool_calls=64,
                    max_tokens=settings.RESEARCH_MODEL_TOTAL_TOKENS,
                    max_runtime_seconds=900,
                ),
                status=ResearchPlanStatus.AWAITING_APPROVAL,
                execution_mode="coordinator",
                source_files=[{"doc_id": d.doc_id, "title": d.title, "version": d.version}
                              for d in manifest.documents],
            )
            return ResearchPlanValidator.validate_or_raise(plan)
        except Exception as exc:
            raise PlannerError("research_planning_failed") from exc

    def _team_tasks(self, request: ResearchRequest, manifest: SourceManifest) -> list[ResearchTask]:
        files = [{"number": i, "title": d.title, "version": d.version}
                 for i, d in enumerate(manifest.documents, 1)]
        data = self._chat({"model": self.model, "temperature": 0.1, "max_tokens": 1800,
            "response_format": {"type": "json_object"}, "messages": [
                {"role": "system", "content":
                 "You are the Research coordinator, planning before any exploration. Receive the user question "
                 "and complete authorized file catalogue. File titles are routing hints, never evidence. "
                 "Return json {\"tasks\":[{\"task_id\":\"task-1\",\"question\":string,\"purpose\":string,"
                 "\"dependencies\":[],\"source_numbers\":[1],\"criteria\":[\"specific requested fact to establish\"]}]}. "
                 "Create 2 to 5 focused tasks for independent explorers. Independent tasks MUST have empty "
                 "dependencies so they can run in parallel. Use dependencies only for necessary prerequisite results. "
                 "Use only file numbers from the catalogue. Cover each requested aspect with concrete acceptance "
                 "criteria. Do not assume a capability, configuration value, error mapping or implementation exists. "
                 "Ask explorers to establish facts or report explicit gaps, historical scope and contradictions. "
                 "The human will edit and approve this exact plan; you will subsequently coordinate, not explore. "
                 "Write task text in English."},
                {"role": "user", "content": json.dumps({"question": request.query, "files": files}, ensure_ascii=False)}]})
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise PlannerError("research_plan_truncated")
        raw = unwrap_json_object(json.loads(choice["message"]["content"]))
        specs = raw.get("tasks", [])
        if not 2 <= len(specs) <= 5:
            raise PlannerError("research_plan_task_count")
        tasks = []
        for index, spec in enumerate(specs, 1):
            numbers = spec.get("source_numbers", [])
            if not numbers or any(type(n) is not int or not 1 <= n <= len(files) for n in numbers):
                raise PlannerError("research_plan_source_outside_catalogue")
            criteria = spec.get("criteria", [])
            if not 1 <= len(criteria) <= 5:
                raise PlannerError("research_plan_criteria_required")
            tasks.append(ResearchTask(task_id=spec.get("task_id", f"task-{index}"),
                question=spec["question"], purpose=spec["purpose"], dependencies=spec.get("dependencies", []),
                source_ids=list(dict.fromkeys(manifest.documents[n - 1].doc_id for n in numbers)),
                allowed_tools=["keyword_search", "read_document_range"], max_actions=6,
                acceptance_criteria=[AcceptanceCriterion(criterion_id=f"criterion-{index}-{j}",
                    dimension="evidence", target=target, required=True) for j, target in enumerate(criteria, 1)]))
        return tasks


    def _chat(self, payload: dict) -> dict:
        payload = dict(payload)
        if self.model.casefold().startswith("deepseek"):
            payload.setdefault("thinking", {"type": "enabled" if settings.LLM_THINKING_MODE == "enabled" else "disabled"})
        payload = with_completion_budget(payload, model=self.model)
        payload = apply_provider_options(payload, self.api_base)
        return post_completion(self.api_base, self.api_key, payload, self.timeout_seconds)


__all__ = ["ModelResearchPlanner", "PlannerError", "ResearchPlanner"]
