from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.schemas.research import (
    ClaimDraft, ClaimVerificationStatus, CoverageResult, Finding, ResearchReport,
    ResearchRequest, ResearchResultStatus, SourceScope, VerificationResult,
)
from deep_research.evidence import EvidenceLedger
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.runtime import ResearchGraphRuntime
from deep_research.service import ResearchControlPlane
from deep_research.structural_verifier import StructuralVerifier
from deep_research.tools import LocalResearchToolAdapter, ManifestAccessError, ToolCallContext


DOCUMENT = {"doc_id": "doc-a", "title": "A", "content": "收入增长。\n利润稳定。", "version": "v1"}


class Search:
    def search(self, query: str, **kwargs):
        assert kwargs["filters"] == {"doc_ids": ["doc-a"]}
        return [
            {"doc_id": "doc-a", "chunk_id": "doc-a::chunk_0", "chunk_index": 0,
             "chunk_text": "收入增长", "score": 0.9},
            {"doc_id": "outside", "chunk_id": "outside::chunk_0", "chunk_index": 0,
             "chunk_text": "越界", "score": 1.0},
        ]


def setup_research(tmp_path):
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    (documents_dir / "doc-a.json").write_text(json.dumps(DOCUMENT, ensure_ascii=False), encoding="utf-8")
    repository = SQLiteResearchRepository(tmp_path / "research.db")
    control = ResearchControlPlane(
        repository,
        source_resolver=InMemoryDocumentResolver({"doc-a": DOCUMENT}),
    )
    job = control.create_job(ResearchRequest(query="分析经营表现", source_scope=SourceScope(document_ids=["doc-a"])), user_id="alice")
    control.approve_job(
        job.research_id, plan_version=job.plan_version,
        manifest_hash=job.manifest_hash, approved_by="alice",
    )
    context = control.claim_for_execution(job.research_id)
    tool_context = ToolCallContext(
        research_id=job.research_id, task_id=context.tasks[0].task_id,
        trace_id="trace-1", user_id="alice", source_manifest=context.manifest,
    )
    return repository, control, documents_dir, context, tool_context


def test_day3_search_is_observation_and_original_read_is_deduplicated_evidence(tmp_path) -> None:
    repository, _, documents_dir, context, tool_context = setup_research(tmp_path)
    adapter = LocalResearchToolAdapter(Search(), documents_dir)
    ledger = EvidenceLedger(repository)
    try:
        hits = adapter.search("收入", tool_context)
        assert [hit.doc_id for hit in hits] == ["doc-a"]
        observations = ledger.record_search("收入", hits, tool_context)
        assert len(observations) == 1
        assert repository.list_evidence(context.job.research_id) == []

        read = adapter.read_document_range("doc-a", tool_context, start_line=1, end_line=1)
        first = ledger.record_original_read(read, tool_context)
        second = ledger.record_original_read(read, tool_context)
        assert first.evidence_id == second.evidence_id
        assert len(repository.list_evidence(context.job.research_id)) == 1
        assert repository.get_job(context.job.research_id).evidence_count == 1
        assert first.locator == "line:1-1"
        with pytest.raises(ManifestAccessError, match="outside_manifest"):
            adapter.read_document_range("outside", tool_context)
    finally:
        adapter.close()


class Pipeline:
    def __init__(self, repository, evidence_id):
        self.repository = repository
        self.evidence_id = evidence_id
        self.semantic_input = []

    def execute_tasks(self, research_id):
        finding = Finding(
            finding_id="finding-1", research_id=research_id, task_id="task-1",
            statement="收入增长", evidence_ids=[self.evidence_id], covers=["task-1-C1"],
        )
        self.repository.save_finding(finding)
        return [finding.finding_id]

    def compute_coverage(self, research_id):
        coverage = CoverageResult(research_id=research_id, covered=["task-1-C1"], missing=[], sufficient=True)
        self.repository.save_coverage(coverage)
        return ["coverage-" + research_id]

    def generate_claims(self, research_id):
        claims = [
            ClaimDraft(claim_id="claim-valid", research_id=research_id, claim_text="收入增长", evidence_ids=[self.evidence_id]),
            ClaimDraft(claim_id="claim-invalid", research_id=research_id, claim_text="编造", evidence_ids=["missing"]),
        ]
        for claim in claims:
            self.repository.save_claim(claim)
        return [claim.claim_id for claim in claims]

    def semantic_verify(self, research_id, claim_ids):
        self.semantic_input = claim_ids
        return [VerificationResult(
            claim_id=claim_id, status=ClaimVerificationStatus.SUPPORTED,
            evidence_ids=[self.evidence_id], reason="fixture",
        ) for claim_id in claim_ids]

    def render_report(self, research_id):
        return ResearchReport(
            report_id="report-1", research_id=research_id, markdown="# 报告\n\n收入增长。[证据 1]",
            result_status=ResearchResultStatus.COMPLETE, claim_ids=["claim-valid"],
            evidence_ids=[self.evidence_id],
        )


def test_day4_structural_gate_graph_checkpoint_and_report(tmp_path) -> None:
    repository, control, documents_dir, context, tool_context = setup_research(tmp_path)
    adapter = LocalResearchToolAdapter(Search(), documents_dir)
    try:
        evidence = EvidenceLedger(repository).record_original_read(
            adapter.read_document_range("doc-a", tool_context, start_line=1, end_line=1), tool_context,
        )
    finally:
        adapter.close()

    pipeline = Pipeline(repository, evidence.evidence_id)
    runtime = ResearchGraphRuntime(control, pipeline, InMemorySaver())
    result = runtime.run(context.job.research_id)

    assert result["current_stage"] == "completed"
    completed = repository.get_job(context.job.research_id)
    assert completed.status.value == "completed"
    assert completed.result_status == ResearchResultStatus.COMPLETE
    assert pipeline.semantic_input == ["claim-valid"]
    invalid = next(item for item in repository.list_verifications(context.job.research_id) if item.claim_id == "claim-invalid")
    assert invalid.status == ClaimVerificationStatus.UNSUPPORTED
    assert "missing_evidence" in invalid.reason
    assert repository.get_report(context.job.research_id).report_id == "report-1"
    checkpoint = repository.get_checkpoint(context.job.research_id)
    assert checkpoint.current_stage == "completed"
    assert "excerpt" not in runtime.state(context.job.research_id).values
