"""Minimal Planner interface for the Local Deep Research control plane."""

from __future__ import annotations

import json
import logging
import time
from agent.config.settings import settings
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
        if not scoped_ids:
            scoped_ids = document_ids
        scoped_documents = [
            document for document in manifest.documents if document.doc_id in scoped_ids
        ]
        source_names = "、".join(f"《{document.title}》" for document in scoped_documents)
        version_focus = "、".join(
            f"《{document.title}》（{document.version or '未标注版本'}）"
            for document in scoped_documents
        )

        tasks = [
            ResearchTask(
                task_id="task-1",
                question=f"分别核验{source_names}中能回答“{request.query}”的具体事实、实现状态和原文位置。",
                purpose=f"为{source_names}分别建立可追溯的证据摘要。",
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-1",
                        dimension="evidence",
                        target=f"{source_names}的具体事实与原文",
                        required=True,
                    )
                ],
                priority=ResearchTaskPriority.CRITICAL,
                max_actions=2,
            ),
            ResearchTask(
                task_id="task-2",
                question=f"对照{version_focus}回答“{request.query}”时的一致点、版本差异和真正的语义冲突。",
                purpose="区分版本演进、适用范围差异和需要用户裁决的事实冲突。",
                dependencies=["task-1"],
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-2",
                        dimension="locator",
                        target="各文档的版本、一致点、差异点与完整原文",
                        required=True,
                    )
                ],
                priority=ResearchTaskPriority.CRITICAL,
                max_actions=4,
            ),
            ResearchTask(
                task_id="task-3",
                question=f"基于{source_names}列出问题中仍无法确认的事项、资料边界和需要补充的证据。",
                purpose="阻止超出已选资料范围的推测进入最终报告。",
                dependencies=["task-2"],
                allowed_tools=["keyword_search", "read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-3",
                        dimension="limitation",
                        target=f"{source_names}未覆盖或无法确认的事项",
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
            "Keep technical identifiers and source-language keywords in task questions "
            "so local lexical search can find the relevant sections. Separate questions "
            "about summary counts, commit details, and changed files when all are requested. "
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
        if settings.LLM_THINKING_MODE in {"enabled", "disabled"}:
            payload["thinking"] = {"type": settings.LLM_THINKING_MODE}
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
        last_error: Exception | None = None
        for attempt in range(2):
            request = Request(
                f"{self.api_base}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("Research planner request failed; retrying once: %s", exc)
                    time.sleep(0.5)
        assert last_error is not None
        raise last_error


__all__ = ["MockResearchPlanner", "ModelResearchPlanner", "PlannerError", "ResearchPlanner"]
