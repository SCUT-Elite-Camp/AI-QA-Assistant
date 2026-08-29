from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.schemas.research import (
    AcceptanceCriterion,
    ClaimVerificationStatus,
    Finding,
    ResearchRequest,
    SourceScope,
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
    assert len(ledger.evidence) == 3
    assert all(item.locator == "page:1/paragraph:1" for item in ledger.evidence.values())
    assert all(
        observation.snippet != evidence.excerpt
        or observation.observation_id != evidence.evidence_id
        for observation in ledger.observations
        for evidence in ledger.evidence.values()
    )
    assert all(finding.evidence_ids for finding in ledger.findings)


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
    assert "未进入确定性正文" in report.markdown
    assert "证据存在冲突" in report.markdown
    assert "E:e1" in report.markdown
