"""Explicit deterministic planner fixture; never imported by application code."""
from agent.config.settings import settings
from deep_research.planner import PlannerError
from agent.schemas.research import (AcceptanceCriterion, ResearchBudget, ResearchPlan, ResearchPlanStatus, ResearchPlanValidator, ResearchRequest, ResearchTask, ResearchTaskPriority, SourceManifest)

class FixtureResearchPlanner:
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
            execution_mode="coordinator",
            source_files=[{"doc_id": d.doc_id, "title": d.title, "version": d.version} for d in manifest.documents],
            tasks=tasks,
            budget=ResearchBudget(
                max_tasks=6,
                max_actions=16,
                max_tool_calls=16,
                max_tokens=settings.RESEARCH_MODEL_TOTAL_TOKENS,
                max_runtime_seconds=300,
            ),
            status=ResearchPlanStatus.AWAITING_APPROVAL,
        )
        try:
            return ResearchPlanValidator.validate_or_raise(plan)
        except ValueError as exc:
            raise PlannerError(str(exc)) from exc


def save_historical_report(repository, report):
    """Inject a historical/corrupt stored row to test read guards, not release."""
    return repository._save_entity("report", report.report_id, report.research_id, report.model_dump_json())
