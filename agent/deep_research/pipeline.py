"""Production adapter joining Research Intelligence to the durable runtime."""

from __future__ import annotations

from collections.abc import Iterable
import re

from agent.schemas.research import (
    ClaimDraft,
    ClaimVerificationStatus,
    ResearchJob,
    ResearchReport,
    ResearchTaskStatus,
    VerificationResult,
    VerifiedClaim,
)

from .claims import ClaimGenerator
from .coverage import CoverageEngine
from .repository import ResearchNotFoundError, SQLiteResearchRepository
from .renderer import MarkdownReportRenderer
from .service import ApprovedResearchContext, ResearchControlPlane
from .tools import LocalResearchToolAdapter, ToolCallContext
from .verifier import DeterministicSemanticVerifier, SemanticVerifier
from .worker import LocalResearchWorker, OriginalRead, ResearchLedger, SearchHit


class ManifestScopedWorkerTools:
    """Translate the A-side Worker protocol to B's manifest-scoped adapter."""

    _LINE_LOCATOR = re.compile(r"^line:(\d+)-(\d+)$")

    def __init__(
        self,
        adapter: LocalResearchToolAdapter,
        context: ApprovedResearchContext,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.adapter = adapter
        self.context = context
        self.timeout_seconds = timeout_seconds
        self._task_ids = {task.task_id for task in context.tasks}
        self._manifest_ids = {item.doc_id for item in context.manifest.documents}

    def _context(
        self,
        *,
        research_id: str,
        task_id: str,
        trace_id: str,
    ) -> ToolCallContext:
        if research_id != self.context.job.research_id:
            raise ValueError("worker research_id differs from approved context")
        if task_id not in self._task_ids:
            raise ValueError("worker task_id is outside the approved Plan")
        return ToolCallContext(
            research_id=research_id,
            task_id=task_id,
            trace_id=trace_id,
            user_id=self.context.job.user_id,
            source_manifest=self.context.manifest,
            timeout_seconds=self.timeout_seconds,
        )

    def search(
        self,
        *,
        query: str,
        source_ids: list[str],
        research_id: str,
        task_id: str,
        trace_id: str,
    ) -> Iterable[SearchHit]:
        outside = set(source_ids) - self._manifest_ids
        if outside:
            raise ValueError(
                "worker source outside SourceManifest: " + ",".join(sorted(outside))
            )
        context = self._context(
            research_id=research_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        hits = self.adapter.search(
            query,
            context,
            top_k=max(1, len(source_ids) * 2),
            source_ids=source_ids,
        )
        return [
            SearchHit(
                doc_id=item.doc_id,
                snippet=item.snippet,
                locator_hint=item.locator_hint,
                score=item.score,
            )
            for item in hits
        ]

    def read_document_range(
        self,
        *,
        doc_id: str,
        locator_hint: str,
        research_id: str,
        task_id: str,
        trace_id: str,
    ) -> OriginalRead:
        context = self._context(
            research_id=research_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        match = self._LINE_LOCATOR.fullmatch(locator_hint.strip())
        start_line = int(match.group(1)) if match else 1
        end_line = int(match.group(2)) if match else None
        item = self.adapter.read_document_range(
            doc_id,
            context,
            start_line=start_line,
            end_line=end_line,
        )
        return OriginalRead(
            doc_id=item.doc_id,
            document_version=item.document_version,
            locator=item.locator,
            excerpt=item.excerpt,
            content_hash=item.content_hash,
        )


class ResearchIntelligencePipeline:
    """Repository-backed implementation of the Graph Intelligence protocol.

    Every stage is idempotent.  A restart may replay a stage, but immutable
    entity IDs ensure that persisted Evidence, Findings, Claims and Reports
    are reused instead of duplicated.
    """

    def __init__(
        self,
        control_plane: ResearchControlPlane,
        tool_adapter: LocalResearchToolAdapter,
        *,
        semantic_verifier: SemanticVerifier | None = None,
        renderer: MarkdownReportRenderer | None = None,
        ledger: ResearchLedger | None = None,
        max_candidates_per_task: int = 2,
    ) -> None:
        self.control_plane = control_plane
        self.repository: SQLiteResearchRepository = control_plane.repository
        self.tool_adapter = tool_adapter
        self.semantic_verifier = semantic_verifier or DeterministicSemanticVerifier()
        self.renderer = renderer or MarkdownReportRenderer()
        self.ledger = ledger or self.repository
        self.max_candidates_per_task = max_candidates_per_task

    def execute_tasks(self, research_id: str) -> list[str]:
        context = self.control_plane.approved_context(research_id)
        existing = self.repository.list_findings(research_id)
        completed_task_ids = {item.task_id for item in existing}
        if completed_task_ids == {task.task_id for task in context.tasks}:
            completed = len(completed_task_ids)
        else:
            worker_tools = ManifestScopedWorkerTools(self.tool_adapter, context)
            result = LocalResearchWorker(
                worker_tools,
                self.ledger,
                max_candidates_per_task=self.max_candidates_per_task,
            ).run(context)
            completed = sum(
                item.status == ResearchTaskStatus.SUCCEEDED
                for item in result.task_results
            )
        job = self.repository.get_job(research_id)
        self.repository.update_job(
            ResearchJob.model_validate(
                {
                    **job.model_dump(),
                    "task_completed": completed,
                    "current_task_id": None,
                }
            )
        )
        return [item.finding_id for item in self.repository.list_findings(research_id)]

    def compute_coverage(self, research_id: str) -> list[str]:
        plan = self.control_plane.get_plan(research_id)
        criteria = [
            criterion
            for task in plan.tasks
            for criterion in task.acceptance_criteria
        ]
        coverage = CoverageEngine().compute(
            research_id,
            criteria,
            self.repository.list_findings(research_id),
        )
        self.repository.save_coverage(coverage)
        return [f"coverage-{research_id}"]

    def generate_claims(self, research_id: str) -> list[str]:
        claims = ClaimGenerator().generate(
            self.repository.list_findings(research_id),
            research_id=research_id,
        )
        for claim in claims:
            self.repository.save_claim(claim)
        return [claim.claim_id for claim in claims]

    def semantic_verify(
        self,
        research_id: str,
        claim_ids: list[str],
    ) -> list[VerificationResult]:
        selected = set(claim_ids)
        claims = [
            claim
            for claim in self.repository.list_claims(research_id)
            if claim.claim_id in selected
        ]
        evidence = self.repository.list_evidence(research_id)
        return [self.semantic_verifier.verify(claim, evidence) for claim in claims]

    def render_report(self, research_id: str) -> ResearchReport:
        try:
            return self.repository.get_report(research_id)
        except ResearchNotFoundError:
            pass

        plan = self.control_plane.get_plan(research_id)
        coverage = self.repository.get_coverage(research_id)
        claims = self.repository.list_claims(research_id)
        verification_by_claim: dict[str, VerificationResult] = {}
        for result in self.repository.list_verifications(research_id):
            verification_by_claim[result.claim_id] = result

        verified: list[VerifiedClaim] = []
        for claim in claims:
            result = verification_by_claim.get(claim.claim_id)
            if result is None:
                result = VerificationResult(
                    claim_id=claim.claim_id,
                    status=ClaimVerificationStatus.UNSUPPORTED,
                    evidence_ids=list(claim.evidence_ids),
                    reason="claim_did_not_pass_structural_verification",
                )
            verified.append(self._verified_claim(claim, result))

        job = self.repository.get_job(research_id)
        limitations: list[str] = []
        if job.task_completed < job.task_total:
            limitations.append(
                f"仅完成 {job.task_completed}/{job.task_total} 个研究任务。"
            )
        return self.renderer.render(
            research_id=research_id,
            objective=plan.objective,
            claims=verified,
            coverage=coverage,
            evidence=self.repository.list_evidence(research_id),
            limitations=limitations,
            title=plan.report_spec.title or None,
        )

    @staticmethod
    def _verified_claim(
        claim: ClaimDraft,
        result: VerificationResult,
    ) -> VerifiedClaim:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            research_id=claim.research_id,
            claim_text=claim.claim_text,
            status=result.status,
            evidence_ids=list(result.evidence_ids),
            criterion_ids=list(claim.criterion_ids),
            reason=result.reason,
        )


__all__ = ["ManifestScopedWorkerTools", "ResearchIntelligencePipeline"]
