"""Citation-preserving Markdown rendering from verified Claims only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from agent.schemas.research import (
    ClaimVerificationStatus,
    CoverageResult,
    ResearchReport,
    ResearchResultStatus,
    VerifiedClaim,
    VerifiedEvidence,
)


class MarkdownReportRenderer:
    """Render existing verified objects; it has no Search or Read capability."""

    def render(
        self,
        *,
        research_id: str,
        objective: str,
        claims: Iterable[VerifiedClaim],
        coverage: CoverageResult,
        evidence: Mapping[str, VerifiedEvidence] | Iterable[VerifiedEvidence] = (),
        limitations: Iterable[str] = (),
        title: str | None = None,
        report_id: str | None = None,
    ) -> ResearchReport:
        claim_list = [claim for claim in claims if claim.research_id == research_id]
        evidence_map = (
            dict(evidence)
            if isinstance(evidence, Mapping)
            else {item.evidence_id: item for item in evidence}
        )
        limitation_list = self._unique_text(limitations)
        lines = [
            f"# {title or objective}",
            "",
            "## 结论",
            "",
        ]

        rendered_claim_count = 0
        referenced_evidence: list[str] = []
        for claim in claim_list:
            citation = self._citation(claim.evidence_ids)
            if claim.status == ClaimVerificationStatus.SUPPORTED:
                lines.append(f"- {claim.claim_text}{citation}")
                rendered_claim_count += 1
            elif claim.status == ClaimVerificationStatus.PARTIAL:
                lines.append(f"- 部分证据支持：{claim.claim_text}{citation}")
                rendered_claim_count += 1
                limitation_list.append(
                    f"{claim.claim_id} 仅获得部分证据支持：{claim.reason or '需进一步核验'}"
                )
            elif claim.status == ClaimVerificationStatus.CONFLICTING:
                lines.append(f"- 证据存在冲突，无法形成确定结论：{claim.claim_text}{citation}")
                rendered_claim_count += 1
                limitation_list.append(
                    f"{claim.claim_id} 的证据存在冲突：{claim.reason or '未选择任一冲突值'}"
                )
            else:
                limitation_list.append(
                    f"{claim.claim_id} 未进入确定性正文：{claim.reason or '缺少充分证据'}"
                )
            for evidence_id in claim.evidence_ids:
                if evidence_id not in referenced_evidence:
                    referenced_evidence.append(evidence_id)

        if rendered_claim_count == 0:
            lines.append("- 当前没有可安全写入确定性正文的结论。")

        lines.extend(
            [
                "",
                "## 覆盖情况",
                "",
                f"- 已覆盖：{', '.join(coverage.covered) or '无'}",
                f"- 缺失：{', '.join(coverage.missing) or '无'}",
            ]
        )
        if coverage.missing:
            limitation_list.append(
                "缺失必需验收条件：" + ", ".join(coverage.missing)
            )

        limitation_list = self._unique_text(limitation_list)
        lines.extend(["", "## 局限性", ""])
        if limitation_list:
            lines.extend(f"- {item}" for item in limitation_list)
        else:
            lines.append("- 暂无已记录局限性。")

        lines.extend(["", "## 证据索引", ""])
        if referenced_evidence:
            for evidence_id in referenced_evidence:
                item = evidence_map.get(evidence_id)
                if item is None:
                    lines.append(f"- {evidence_id}")
                else:
                    lines.append(
                        f"- {evidence_id}：{item.doc_id} / {item.locator}"
                    )
        else:
            lines.append("- 无")

        all_supported = all(
            claim.status == ClaimVerificationStatus.SUPPORTED
            for claim in claim_list
            if claim.status != ClaimVerificationStatus.UNSUPPORTED
        )
        result_status = (
            ResearchResultStatus.COMPLETE
            if coverage.sufficient and all_supported and not limitation_list
            else ResearchResultStatus.DEGRADED
        )
        return ResearchReport(
            report_id=report_id or f"report-{research_id}",
            research_id=research_id,
            markdown="\n".join(lines).strip() + "\n",
            result_status=result_status,
            claim_ids=[claim.claim_id for claim in claim_list],
            evidence_ids=referenced_evidence,
        )

    @staticmethod
    def _citation(evidence_ids: Iterable[str]) -> str:
        ids = list(evidence_ids)
        return " " + " ".join(f"[E:{evidence_id}]" for evidence_id in ids) if ids else ""

    @staticmethod
    def _unique_text(values: Iterable[str]) -> list[str]:
        output: list[str] = []
        for value in values:
            normalized = " ".join(str(value).strip().split())
            if normalized and normalized not in output:
                output.append(normalized)
        return output


def render_markdown_report(
    *,
    research_id: str,
    objective: str,
    claims: Iterable[VerifiedClaim],
    coverage: CoverageResult,
    evidence: Mapping[str, VerifiedEvidence] | Iterable[VerifiedEvidence] = (),
    limitations: Iterable[str] = (),
    title: str | None = None,
) -> ResearchReport:
    return MarkdownReportRenderer().render(
        research_id=research_id,
        objective=objective,
        claims=claims,
        coverage=coverage,
        evidence=evidence,
        limitations=limitations,
        title=title,
    )


__all__ = ["MarkdownReportRenderer", "render_markdown_report"]
