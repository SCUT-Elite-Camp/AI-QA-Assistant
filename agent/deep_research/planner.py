"""Minimal Planner interface for the Local Deep Research control plane."""

from __future__ import annotations

from typing import Protocol

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


class MockResearchPlanner:
    """Deterministic Planner used until an LLM-backed Planner is integrated.

    It intentionally creates a small serial plan.  The important Week 2
    contract is the shape and validation boundary, not model creativity.
    """

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
                question=f"定位与研究目标直接相关的原始事实：{request.query}",
                purpose="从冻结资料范围中定位候选原文。",
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
                max_actions=4,
            ),
            ResearchTask(
                task_id="task-2",
                question="读取并核验候选事实对应的原始文档位置。",
                purpose="将搜索观察转换为可定位的原文证据。",
                dependencies=["task-1"],
                allowed_tools=["read_document_range"],
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
                question="整理研究结论，并标记资料范围内无法确认的内容。",
                purpose="为后续 Coverage 和报告生成提供结论与局限。",
                dependencies=["task-2"],
                allowed_tools=["read_document_range"],
                source_ids=scoped_ids,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        criterion_id="criterion-3",
                        dimension="limitation",
                        target="资料限制",
                        required=True,
                    )
                ],
                priority=ResearchTaskPriority.NORMAL,
                max_actions=4,
            ),
        ]

        plan = ResearchPlan(
            schema_version="research.v2",
            research_id=manifest.research_id,
            version=version,
            objective=request.query,
            out_of_scope=["Web Research", "未列入 SourceManifest 的文档"],
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


__all__ = ["MockResearchPlanner", "PlannerError", "ResearchPlanner"]
