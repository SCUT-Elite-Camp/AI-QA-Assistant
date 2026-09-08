"""Minimal Planner interface for the Local Deep Research control plane."""

from __future__ import annotations

import json
import logging
from typing import Protocol
from urllib.request import Request, urlopen

from agent.schemas.research import (
    AcceptanceCriterion,
    ResearchBudget,
    ResearchPlan,
    ResearchPlanStatus,
    ResearchPlanValidator,
    ResearchRequest,
    ResearchTask,
    ResearchTaskPriority,
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


logger = logging.getLogger(__name__)


class MockResearchPlanner:
    """Bounded deterministic planner used for both local and online sources."""

    def create_plan(
        self,
        request: ResearchRequest,
        manifest: SourceManifest,
        *,
        version: int = 1,
    ) -> ResearchPlan:
        document_ids = [document.doc_id for document in manifest.documents]
        scoped_ids = [
            doc_id
            for doc_id in document_ids
            if doc_id in request.source_scope.allowed_source_ids()
        ]

        tasks = [
            ResearchTask(
                task_id="task-1",
                question=f"从已冻结来源中定位与问题直接相关的核心事实：{request.query}",
                purpose="定位可引用的一手事实和原文。",
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-1",
                        dimension="evidence",
                        target="核心事实",
                        required=True,
                    )
                ],
                priority=ResearchTaskPriority.CRITICAL,
                max_actions=2,
            ),
            ResearchTask(
                task_id="task-2",
                question=f"交叉比较不同来源的关键事实、时间和口径，识别冲突：{request.query}",
                purpose="交叉核验来源，并显式保留不一致信息。",
                dependencies=["task-1"],
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-2",
                        dimension="locator",
                        target="原文位置",
                        required=True,
                    )
                ],
                priority=ResearchTaskPriority.CRITICAL,
                max_actions=4,
            ),
            ResearchTask(
                task_id="task-3",
                question="核对资料边界、缺失条件、过期内容和无法确认事项，再整理结论。",
                purpose="为后续 Coverage 和报告生成提供结论与局限。",
                dependencies=["task-2"],
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-3",
                        dimension="limitation",
                        target="资料限制",
                        required=False,
                    )
                ],
                priority=ResearchTaskPriority.NORMAL,
                max_actions=2,
            ),
        ]

        plan = ResearchPlan(
            schema_version="research.v2",
            research_id=manifest.research_id,
            version=version,
            objective=request.query,
            out_of_scope=["未列入 SourceManifest 的资料", "无法从原文核验的推测"],
            source_scope=request.source_scope,
            report_spec=request.report_spec,
            manifest_hash=manifest.manifest_hash,
            tasks=tasks,
            budget=ResearchBudget(
                max_tasks=6,
                max_actions=16,
                max_tool_calls=16,
                max_tokens=12_000,
                max_runtime_seconds=300,
            ),
            status=ResearchPlanStatus.AWAITING_APPROVAL,
        )
        try:
            return ResearchPlanValidator.validate_or_raise(plan)
        except ValueError as exc:
            raise PlannerError(str(exc)) from exc


class ModelResearchPlanner:
    """Generate a query-specific bounded plan, with a safe deterministic fallback."""

    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        fallback: ResearchPlanner | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback or MockResearchPlanner()

    def create_plan(
        self,
        request: ResearchRequest,
        manifest: SourceManifest,
        *,
        version: int = 1,
    ) -> ResearchPlan:
        if not self.api_key:
            logger.warning("Research planner is using fallback because the API key is empty")
            return self.fallback.create_plan(request, manifest, version=version)
        try:
            tasks = self._generate_tasks(request, manifest)
            plan = ResearchPlan(
                schema_version="research.v2",
                research_id=manifest.research_id,
                version=version,
                objective=request.query,
                out_of_scope=["未列入 SourceManifest 的资料", "无法从原文核验的推测"],
                source_scope=request.source_scope,
                report_spec=request.report_spec,
                manifest_hash=manifest.manifest_hash,
                tasks=tasks,
                budget=ResearchBudget(
                    max_tasks=6,
                    max_actions=24,
                    max_tool_calls=24,
                    max_tokens=12_000,
                    max_runtime_seconds=300,
                ),
                status=ResearchPlanStatus.AWAITING_APPROVAL,
            )
            return ResearchPlanValidator.validate_or_raise(plan)
        except Exception as exc:
            logger.warning("Research planner model failed; using fallback: %s", exc)
            return self.fallback.create_plan(request, manifest, version=version)

    def _generate_tasks(
        self, request: ResearchRequest, manifest: SourceManifest
    ) -> list[ResearchTask]:
        documents = [
            {
                "doc_id": item.doc_id,
                "title": item.title,
                "source_type": item.source_type,
                "version": item.version,
                "effective_at": item.effective_at,
            }
            for item in manifest.documents
        ]
        language = "Chinese" if request.report_spec.language == "zh-CN" else "English"
        prompt = (
            "Create a specific research plan for the question and frozen local documents below. "
            "Return JSON only: {\"tasks\":[{\"question\":string,\"purpose\":string,"
            "\"acceptance_target\":string}]}. Create 2 to 5 non-overlapping tasks in execution order. "
            "Tasks must name the concrete facts, comparisons, dates, versions, or uncertainties to verify; "
            "do not use generic phrases such as locate core facts or organize conclusions. "
            f"Write task text in {language}. Do not browse or add sources.\n\n"
            f"Question: {request.query}\n"
            f"Documents: {json.dumps(documents, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        raw = self._chat(payload)["choices"][0]["message"]["content"]
        parsed = json.loads(str(raw).strip().removeprefix("```json").removesuffix("```").strip())
        specs = parsed.get("tasks")
        if not isinstance(specs, list) or not 2 <= len(specs) <= 5:
            raise PlannerError("model must return 2 to 5 tasks")
        source_ids = [item.doc_id for item in manifest.documents]
        tasks: list[ResearchTask] = []
        for index, spec in enumerate(specs, start=1):
            if not isinstance(spec, dict):
                raise PlannerError("task must be an object")
            question = str(spec.get("question", "")).strip()
            purpose = str(spec.get("purpose", "")).strip()
            target = str(spec.get("acceptance_target", "")).strip()
            if min(len(question), len(purpose), len(target)) < 4:
                raise PlannerError("model returned an incomplete task")
            tasks.append(
                ResearchTask(
                    task_id=f"task-{index}",
                    question=question,
                    purpose=purpose,
                    dependencies=[] if index == 1 else [f"task-{index - 1}"],
                    allowed_tools=["keyword_search", "read_document_range"],
                    source_ids=source_ids,
                    acceptance_criteria=[
                        AcceptanceCriterion(
                            criterion_id=f"criterion-{index}",
                            dimension="evidence",
                            target=target,
                            required=True,
                        )
                    ],
                    priority=(
                        ResearchTaskPriority.CRITICAL
                        if index <= 2
                        else ResearchTaskPriority.NORMAL
                    ),
                    max_actions=4,
                )
            )
        return tasks

    def _chat(self, payload: dict) -> dict:
        request = Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


__all__ = ["MockResearchPlanner", "ModelResearchPlanner", "PlannerError", "ResearchPlanner"]
