"""Minimal Planner interface for the Local Deep Research control plane."""

from __future__ import annotations

import json
import logging
import time
from agent.config.settings import settings
from agent.llm.provider_options import apply_provider_options
import re
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
        # The manifest is the complete search boundary, not a requirement to
        # read every document. Keep fallback instructions bounded for large KBs.
        names = (", ".join(document.title for document in scoped_documents)[:160]
                 if len(scoped_documents) <= 4
                 else f"{len(scoped_documents)} authorized documents")
        subject = request.query[:700]
        descriptions = [
            (f'Verify facts, implementation status and original locators in {names} that answer "{subject}".',
             "Find relevant source passages and establish traceable evidence.",
             "Specific facts with cited original excerpts", "evidence", 2, True),
            (f'Compare relevant source versions, agreements and semantic conflicts when answering "{subject}".',
             "Distinguish changes over time and scope differences from factual conflicts.",
             "Document versions, agreements, differences and original excerpts", "locator", 4, True),
            (f'Identify unanswered parts, evidence boundaries and additional evidence required for "{subject}".',
             "Record evidence gaps without inferring facts from source silence.",
             "Items not covered or established by available sources", "limitation", 2, False),
        ]
        tasks = [ResearchTask(
            task_id=f"task-{index}", question=question, purpose=purpose,
            dependencies=[] if index == 1 else [f"task-{index - 1}"],
            allowed_tools=["keyword_search", "read_document_range"], source_ids=scoped_ids,
            acceptance_criteria=[AcceptanceCriterion(
                criterion_id=f"criterion-{index}", dimension=dimension,
                target=target, required=required,
            )],
            priority=ResearchTaskPriority.CRITICAL if required else ResearchTaskPriority.NORMAL,
            max_actions=actions,
        ) for index, (question, purpose, target, dimension, actions, required)
          in enumerate(descriptions, start=1)]

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
            self._validate_task_coverage(request.query, tasks)
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
        language = "English"
        prompt = (
            "Create a specific research plan for the question and frozen local documents below. "
            "Return JSON only: {\"tasks\":[{\"question\":string,\"purpose\":string}]}. "
            "Create 2 to 5 non-overlapping tasks in execution order. "
            "Document titles and metadata do not establish their contents. Never predict source findings. "
            "Tasks must name the concrete facts, comparisons, dates, versions, or uncertainties to verify; "
            "do not use generic phrases such as locate core facts or organize conclusions. "
            "Keep technical identifiers and source-language keywords in task questions "
            "so local lexical search can find the relevant sections. Separate questions "
            "about summary counts, commit details, and changed files when all are requested. "
            "Cover every requested comparison and remaining limitation explicitly. "
            "Preserve arithmetic conditions exactly: a minimum for features plus bug fixes is a combined minimum, "
            "never a feature-only minimum. Read canonical totals rather than recounting partial commit history. "
            "Use neutral verification questions: do not assume dependencies were resolved, "
            "planned work was completed, or a working frontend-to-backend demo proves independence "
            "from external services. Distinguish document snapshot/version dates from the event "
            "dates in the document; verify the event dates from source text. For development "
            "over time, check limitations in the later source and whether earlier dependencies "
            "were explicitly resolved, rather than treating historical gaps as current facts. "
            f"Write task text in {language}. Do not browse or add sources.\n\n"
            f"Question: {request.query}\n"
            f"Documents: {json.dumps(documents, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.partition("\n\nQuestion:")[0]},
                {"role": "user", "content": "Question:" + prompt.partition("\n\nQuestion:")[2]},
            ],
            "temperature": 0.1,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        if settings.LLM_THINKING_MODE in {"enabled", "disabled"}:
            payload["thinking"] = {"type": settings.LLM_THINKING_MODE}
        if self.model.casefold().startswith(("qwen", "deepseek")):
            payload['enable_thinking'] = settings.LLM_THINKING_MODE == 'enabled'
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
            target = (
                "Cited original excerpts answer this task, separating confirmed facts, "
                "planned work and unknown status; source silence is not proof of absence."
            )
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

    @classmethod
    def _validate_task_coverage(cls, objective: str, tasks: list[ResearchTask]) -> None:
        """Reject generic model plans that do not mention the user's subject."""

        combined = " ".join(
            f"{task.question} {task.purpose} "
            + " ".join(item.target for item in task.acceptance_criteria)
            for task in tasks
        ).casefold()
        objective_terms = {
            term.casefold()
            for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", objective)
        }
        generic = (
            "locate core facts", "organize conclusions", "定位核心事实",
            "整理研究结论", "收集相关信息",
        )
        if any(marker in combined for marker in generic):
            raise PlannerError("model returned a generic research plan")
        if re.search(r'features\s*(?:plus|\+)\s*bug fixes',objective,re.I):
            if re.search(r'\bminimum(?:\s+of)?\s+\d+\s+features\b|\bfeatures\s*(?:>=|≥)\s*\d+',combined):
                raise PlannerError('research plan changes a combined minimum into a feature-only minimum')
        for marker in ("independence", "fully internal", "offline operation"):
            if marker in combined and marker not in objective.casefold():
                raise PlannerError("research plan introduces an unrequested independence claim")
        if objective_terms and not any(term in combined for term in objective_terms):
            raise PlannerError("research plan does not cover the objective")

    def _chat(self, payload: dict) -> dict:
        from .access import check_research_model_access
        payload = apply_provider_options(payload, self.api_base)
        last_error: Exception | None = None
        for attempt in range(2):
            check_research_model_access()
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
                    result = json.loads(response.read().decode("utf-8"))
                    check_research_model_access()
                    return result
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("Research planner request failed; retrying once: %s", exc)
                    time.sleep(0.5)
        assert last_error is not None
        raise last_error


__all__ = ["MockResearchPlanner", "ModelResearchPlanner", "PlannerError", "ResearchPlanner"]
