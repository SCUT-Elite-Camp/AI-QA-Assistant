from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from agent.schemas.research import (
    AcceptanceCriterion,
    ClaimDraft,
    ClaimVerificationStatus,
    Finding,
    ResearchRequest,
    SourceScope,
    VerifiedClaim,
    VerifiedEvidence,
)
from deep_research.claims import ClaimGenerator
from deep_research.coverage import CoverageEngine
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.renderer import MarkdownReportRenderer
from deep_research.service import ResearchControlPlane
from deep_research.verifier import DeterministicSemanticVerifier
from deep_research.worker import InMemoryResearchLedger, LocalResearchWorker


def test_worker_expands_search_hit_to_a_substantive_context_window() -> None:
    assert LocalResearchWorker._expand_locator("line:1-1") == "line:1-17"
    assert LocalResearchWorker._expand_locator("line:20-20") == "line:4-36"


def test_day3_day4_fixture_contains_the_four_required_quality_cases() -> None:
    fixture_path = Path(__file__).resolve().parents[2] / "mock" / "research_day3_day4_cases.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "research.v2"
    assert set(payload["cases"]) == {
        "single_document_fact",
        "two_document_comparison",
        "insufficient_material",
        "conflicting_evidence",
    }
    for case in payload["cases"].values():
        assert case["request"]["source_scope"]["document_ids"]
        assert case["manifest_documents"]
        assert case["plan_tasks"]
        assert "expected_coverage" in case
        assert "expected_claim_status" in case


class FixedResearchTools:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.read_calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.search_calls.append(kwargs)
        return [
            {
                "doc_id": "doc-a",
                "chunk_id": "doc-a::chunk-0",
                "chunk_text": "收入为 10，原始资料未提供风险说明。",
                "score": 0.95,
            }
        ]

    def read_document_range(self, **kwargs: Any) -> dict[str, Any]:
        self.read_calls.append(kwargs)
        return {
            "doc_id": kwargs["doc_id"],
            "version": "v1",
            "locator": "page:1/paragraph:1",
            "excerpt": "收入为 10，原始资料未提供风险说明。",
        }


def _approved_context(tmp_path: Path):
    control_plane = ResearchControlPlane(
        SQLiteResearchRepository(tmp_path / "research.db"),
        source_resolver=InMemoryDocumentResolver(
            {
                "doc-a": {
                    "doc_id": "doc-a",
                    "title": "A",
                    "content": "收入为 10，原始资料未提供风险说明。",
                }
            }
        ),
    )
    job = control_plane.create_job(
        ResearchRequest(
            query="研究 A 的核心指标和资料限制",
            source_scope=SourceScope(document_ids=["doc-a"]),
        )
    )
    return control_plane.claim_for_execution(
        control_plane.approve_job(
            job.research_id,
            plan_version=1,
            manifest_hash=job.manifest_hash or "",
            approved_by="alice",
        ).research_id
    )


def test_worker_uses_approved_real_entities_and_separates_observation_from_evidence(
    tmp_path: Path,
) -> None:
    context = _approved_context(tmp_path)
    tools = FixedResearchTools()
    ledger = InMemoryResearchLedger()
    result = LocalResearchWorker(tools, ledger).run(context)

    assert result.research_id == context.job.research_id
    assert result.succeeded is True
    assert len(result.task_results) == len(context.tasks) == 3
    assert len(tools.search_calls) == 3
    assert len(tools.read_calls) == 3
    for call in tools.search_calls:
        assert call["research_id"] == context.job.research_id
        assert call["source_ids"] == ["doc-a"]
    for outcome in result.task_results:
        assert outcome.actions_used <= 4
        assert outcome.observation_ids
        assert outcome.evidence_ids
        assert outcome.finding_ids

    assert len(ledger.observations) == 3
    assert all(item.score == 0.95 for item in ledger.observations)
    assert len(ledger.evidence) == 3
    assert all(item.locator == "page:1/paragraph:1" for item in ledger.evidence.values())
    assert all(
        observation.snippet != evidence.excerpt
        or observation.observation_id != evidence.evidence_id
        for observation in ledger.observations
        for evidence in ledger.evidence.values()
    )
    assert all(finding.evidence_ids for finding in ledger.findings)


@pytest.mark.parametrize('planner_question',[
    'Give lifetime commits and all sprints with recorded commits.',
    'Read the module archive and compare its recorded activity.',
])
def test_lifetime_question_reads_authoritative_summary_before_partial_history(tmp_path,planner_question):
    from dataclasses import replace
    context=_approved_context(tmp_path)
    context=replace(context,job=context.job.model_copy(update={'request':context.job.request.model_copy(
        update={'query':'Give lifetime commits and all sprints with recorded commits.'})}))
    task=context.tasks[0].model_copy(update={'question':planner_question})
    class RankedHistoryTools(FixedResearchTools):
        def search(self, **kwargs):
            return [{'doc_id':'doc-a','chunk_id':'doc-a_chunk_3','chunk_text':'Partial old commit list', 'score':0.9},
                    {'doc_id':'forbidden','chunk_id':'forbidden_chunk_3','chunk_text':'Must never read','score':1.0}]
        def read_document_range(self, **kwargs):
            self.read_calls.append(kwargs)
            return {'doc_id':kwargs['doc_id'],'locator':kwargs['locator_hint'],'excerpt':
                'Lifetime commits: 20. Sprint summary: W27 11, W32 4.' if kwargs['locator_hint'].endswith('_0') else 'Partial history: W27 8, W32 3.'}
    tools=RankedHistoryTools();ledger=InMemoryResearchLedger()
    result=LocalResearchWorker(tools,ledger)._execute_task(context,task)
    assert tools.read_calls[0]['locator_hint']=='doc-a_chunk_0'
    assert all(call['doc_id']=='doc-a' for call in tools.read_calls)
    assert any('W27 11' in item.excerpt for item in ledger.evidence.values())
    assert result.actions_used<=task.max_actions


def test_total_commits_question_reads_header_instead_of_ranked_chronology(tmp_path):
    from dataclasses import replace
    context = _approved_context(tmp_path)
    context = replace(context, job=context.job.model_copy(update={'request':context.job.request.model_copy(update={
        'query':'Compare Total Commits for W01 and W02 Master Sprints.'})}))
    task = context.tasks[0].model_copy(update={'question':'Read the recorded project values.', 'max_actions':2})
    class ChronologyTools(FixedResearchTools):
        def search(self, **kwargs):
            return [{'doc_id':'doc-a','chunk_id':'doc-a_chunk_7','chunk_text':'22 chronology entries', 'score':1.0},
                    {'doc_id':'forbidden','chunk_id':'forbidden_chunk_0','chunk_text':'Never authorized','score':2.0}]
    tools=ChronologyTools()
    result=LocalResearchWorker(tools,InMemoryResearchLedger())._execute_task(context,task)
    assert [(row['doc_id'],row['locator_hint']) for row in tools.read_calls]==[('doc-a','doc-a_chunk_0')]
    assert result.actions_used<=task.max_actions


def test_two_document_narrative_keeps_ranked_discussion_and_action_items(tmp_path):
    from dataclasses import replace
    context = _approved_context(tmp_path)
    second = context.manifest.documents[0].model_copy(update={'doc_id':'doc-b'})
    context = replace(context, manifest=context.manifest.model_copy(update={'documents':[*context.manifest.documents,second]}))
    task = context.tasks[0].model_copy(update={'question':'Compare the plan with the later demonstration and repair action items.', 'source_ids':['doc-a','doc-b'], 'max_actions':3})
    class NarrativeTools(FixedResearchTools):
        def search(self, **kwargs):
            return [{'doc_id':'doc-a','chunk_id':'doc-a_chunk_3','chunk_text':'Relevant plan','score':0.9},
                    {'doc_id':'doc-b','chunk_id':'doc-b_chunk_2','chunk_text':'Demo and repair actions','score':0.8}]
    tools = NarrativeTools()
    result = LocalResearchWorker(tools,InMemoryResearchLedger())._execute_task(context,task)
    assert [(call['doc_id'],call['locator_hint']) for call in tools.read_calls] == [('doc-a','doc-a_chunk_3'),('doc-b','doc-b_chunk_2')]
    assert result.actions_used <= task.max_actions


def test_commit_identity_reads_requested_module_before_high_ranked_distractors(tmp_path):
    from dataclasses import replace
    context = _approved_context(tmp_path)
    template = context.manifest.documents[0]
    documents = [template.model_copy(update={'doc_id':identifier,'title':title}) for identifier,title in
        [('master','Sprint 2030-W01 Master Report'),('other','Sprint 2030-W02 Example Report'),
         ('doc-a','Sprint 2030-W01 Example Module Deliverables')]]
    context = replace(context,manifest=context.manifest.model_copy(update={'documents':documents}),
        job=context.job.model_copy(update={'request':context.job.request.model_copy(update={
            'query':'Who committed the W01 Example query parser, and on what date? Also give total commits.'})}))
    task = context.tasks[0].model_copy(update={'source_ids':['master','other','doc-a'],'max_actions':2})
    class DistractorTools(FixedResearchTools):
        def search(self, **kwargs):
            return [{'doc_id':identifier,'chunk_id':identifier+'_chunk_4','chunk_text':'Similar commit','score':score}
                for identifier,score in [('master',1.0),('other',0.9),('doc-a',0.8),('forbidden',1.1)]]
    tools = DistractorTools()
    result = LocalResearchWorker(tools,InMemoryResearchLedger())._execute_task(context,task)
    assert [(call['doc_id'],call['locator_hint']) for call in tools.read_calls] == [('doc-a','doc-a_chunk_0')]
    assert result.actions_used <= task.max_actions


def test_coverage_is_deterministic_and_requires_finding_evidence() -> None:
    criteria = [
        AcceptanceCriterion(
            criterion_id="c1",
            dimension="metric",
            target="revenue",
            required=True,
        ),
        AcceptanceCriterion(
            criterion_id="c2",
            dimension="risk",
            target="risk",
            required=True,
        ),
        AcceptanceCriterion(
            criterion_id="c3",
            dimension="optional",
            target="optional detail",
            required=False,
        ),
    ]
    findings = [
        Finding(
            finding_id="f1",
            research_id="r1",
            task_id="t1",
            statement="revenue is supported",
            evidence_ids=["e1"],
            covers=["c1", "c2"],
        ),
        Finding(
            finding_id="f2",
            research_id="r1",
            task_id="t2",
            statement="mapping without evidence",
            evidence_ids=[],
            covers=["c3"],
        ),
    ]

    coverage = CoverageEngine().compute("r1", criteria, findings)

    assert coverage.covered == ["c1", "c2"]
    assert coverage.missing == []
    assert coverage.sufficient is True
    assert coverage.criteria[-1].covered is False


def test_claim_verification_and_renderer_never_promote_unsupported_fact() -> None:
    evidence = [
        VerifiedEvidence(
            evidence_id="e1",
            research_id="r1",
            task_id="t1",
            doc_id="doc-a",
            document_version="v1",
            locator="page:1",
            excerpt="2025 revenue was 10 million.",
            content_hash="12345678",
        ),
        VerifiedEvidence(
            evidence_id="e2",
            research_id="r1",
            task_id="t1",
            doc_id="doc-a",
            document_version="v1",
            locator="page:2",
            excerpt="2025 revenue was 20 million.",
            content_hash="87654321",
        ),
    ]
    findings = [
        Finding(
            finding_id="f-supported",
            research_id="r1",
            task_id="t1",
            statement="2025 revenue was 10 million.",
            evidence_ids=["e1"],
            covers=["c1"],
        ),
        Finding(
            finding_id="f-unsupported",
            research_id="r1",
            task_id="t1",
            statement="2025 revenue was 99 million.",
            evidence_ids=["e1"],
            covers=[],
        ),
        Finding(
            finding_id="f-conflict",
            research_id="r1",
            task_id="t1",
            statement="2025 revenue was 10 million.",
            evidence_ids=["e1", "e2"],
            covers=[],
        ),
    ]
    claims = ClaimGenerator().generate(findings, research_id="r1")
    verified = DeterministicSemanticVerifier().verify_many(claims, evidence)
    by_id = {claim.claim_id: claim for claim in verified}

    assert by_id["claim-f-supported"].status == ClaimVerificationStatus.SUPPORTED
    assert by_id["claim-f-unsupported"].status == ClaimVerificationStatus.UNSUPPORTED
    assert by_id["claim-f-conflict"].status == ClaimVerificationStatus.CONFLICTING

    coverage = CoverageEngine().compute(
        "r1",
        [AcceptanceCriterion(criterion_id="c1", target="revenue", required=True)],
        findings[:1],
    )
    report = MarkdownReportRenderer().render(
        research_id="r1",
        objective="验证收入",
        claims=verified,
        coverage=coverage,
        evidence=evidence,
    )
    assert "2025 revenue was 99 million." not in report.markdown
    assert "部分候选结论因证据不足，未写入结论" in report.markdown
    assert "## 资料冲突" in report.markdown
    assert "[1]" in report.markdown
    assert "claim-f-" not in report.markdown
    assert "evidence_contains_" not in report.markdown


def test_renderer_preserves_unclaimed_verified_evidence_as_supporting_material() -> None:
    evidence = [
        VerifiedEvidence(
            evidence_id="e-used",
            research_id="r-supporting",
            task_id="t1",
            doc_id="doc-a",
            locator="line:1-3",
            excerpt="The implemented workflow has durable checkpoints.",
            content_hash="used-hash",
        ),
        VerifiedEvidence(
            evidence_id="e-extra",
            research_id="r-supporting",
            task_id="t2",
            doc_id="doc-b",
            locator="line:8-12",
            excerpt="The document does not provide production performance results.",
            content_hash="extra-hash",
        ),
    ]
    claims = ClaimGenerator().generate(
        [
            Finding(
                finding_id="f-used",
                research_id="r-supporting",
                task_id="t1",
                statement=evidence[0].excerpt,
                evidence_ids=["e-used"],
                covers=["c1"],
            )
        ],
        research_id="r-supporting",
    )
    verified = DeterministicSemanticVerifier().verify_many(claims, evidence)
    coverage = CoverageEngine().compute(
        "r-supporting",
        [AcceptanceCriterion(criterion_id="c1", target="workflow", required=True)],
        [
            Finding(
                finding_id="f-used",
                research_id="r-supporting",
                task_id="t1",
                statement=evidence[0].excerpt,
                evidence_ids=["e-used"],
                covers=["c1"],
            )
        ],
    )

    report = MarkdownReportRenderer().render(
        research_id="r-supporting",
        objective="Review the workflow",
        claims=verified,
        coverage=coverage,
        evidence=evidence,
    )

    assert len(report.citations) == 2
    assert report.evidence_ids == ["e-used", "e-extra"]
    assert "## 补充核验证据" in report.markdown
    assert "production performance results" in report.markdown


def test_renderer_bounds_long_source_boundary_messages() -> None:
    claim = VerifiedClaim(
        claim_id="claim-long-boundary",
        research_id="r-long-boundary",
        claim_text="资料边界：" + ("架构信息" * 700),
        evidence_ids=[],
        criterion_ids=[],
        status=ClaimVerificationStatus.PARTIAL,
        reason="source boundary",
    )
    coverage = CoverageEngine().compute("r-long-boundary", [], [])

    report = MarkdownReportRenderer().render(
        research_id="r-long-boundary",
        objective="确认当前架构",
        claims=[claim],
        coverage=coverage,
        evidence=[],
    )

    boundary = next(item for item in report.limitations if item.code == "source_boundary")
    assert len(boundary.message) == 2_000
    assert boundary.message.endswith("…")


def test_comparative_evidence_is_not_misclassified_as_a_conflict() -> None:
    evidence = [
        VerifiedEvidence(
            evidence_id="e-w30", research_id="r-compare", task_id="t1",
            doc_id="w30", locator="line:1-4",
            excerpt="W30 had 9 commits, 5 features, and 1 bug fix.",
            content_hash="hash-w30",
        ),
        VerifiedEvidence(
            evidence_id="e-w34", research_id="r-compare", task_id="t1",
            doc_id="w34", locator="line:1-4",
            excerpt="W34 had 8 commits, 3 features, and 5 bug fixes.",
            content_hash="hash-w34",
        ),
    ]
    claim = ClaimDraft(
        claim_id="claim-comparison", research_id="r-compare",
        # The production Worker may preserve one source excerpt as the Claim
        # text even though both periods are attached as evidence.
        claim_text="W34 had 8 commits, 3 features, and 5 bug fixes.",
        evidence_ids=["e-w30", "e-w34"], criterion_ids=["c1"],
    )

    result = DeterministicSemanticVerifier().verify(claim, evidence)

    assert result.status != ClaimVerificationStatus.CONFLICTING


def test_dated_snapshots_do_not_turn_historical_counts_into_current_conflicts():
    evidence = [VerifiedEvidence(evidence_id=f'e-{i}', research_id='r-dates', task_id='t1', doc_id=f'doc-{i}', locator='line:1', excerpt=text, document_version=date, content_hash=f'hash-{i}-12345678') for i, (text, date) in enumerate([
        ('Integration has 2 pending dependencies.', '2027-01-10T10:00:00Z'),
        ('Integration has 1 pending dependency.', '2027-03-15T10:00:00Z'),
    ])]
    claim = ClaimDraft(claim_id='c', research_id='r-dates', claim_text='Integration has 1 pending dependency.', evidence_ids=['e-0', 'e-1'], criterion_ids=['criterion'])
    assert DeterministicSemanticVerifier().verify(claim, evidence).status != ClaimVerificationStatus.CONFLICTING
    # Genuine disagreement about one snapshot must still be surfaced.
    evidence[1] = evidence[1].model_copy(update={'document_version': evidence[0].document_version})
    assert DeterministicSemanticVerifier().verify(claim, evidence).status == ClaimVerificationStatus.CONFLICTING


def test_semantic_verifier_ignores_numeric_prefixes_in_document_ids() -> None:
    evidence = [
        VerifiedEvidence(
            evidence_id="e-a", research_id="r-ids", task_id="t1",
            doc_id="doc-a", locator="line:1-2",
            excerpt="W34 Total Commits: 8; New Features: 3; Bug Fixes: 5.",
            content_hash="hash-a-12345678",
        ),
        VerifiedEvidence(
            evidence_id="e-b", research_id="r-ids", task_id="t1",
            doc_id="doc-b", locator="line:1-2",
            excerpt="W30 Total Commits: 9; New Features: 5; Bug Fixes: 1.",
            content_hash="hash-b-12345678",
        ),
    ]
    claim = ClaimDraft(
        claim_id="claim-document-id-prefix", research_id="r-ids",
        claim_text=(
            "候选资料数值不同：54892d2bcaa53239e12a0013a309806a 为 8、3、5；"
            "833ac861944160a33080f47f6a0d0302 为 9、5、1。"
        ),
        evidence_ids=["e-a", "e-b"], criterion_ids=["c1"],
    )

    result = DeterministicSemanticVerifier().verify(claim, evidence)

    assert result.reason != "claim_numeric_detail_not_fully_present_in_evidence"


def test_finding_builder_bounds_expanded_adjacent_chunk_context() -> None:
    statement = "可核验原文。" * 1000

    bounded = LocalResearchWorker._bounded_finding_statement(statement)

    assert len(bounded) == 4000
    assert bounded.endswith("...")
