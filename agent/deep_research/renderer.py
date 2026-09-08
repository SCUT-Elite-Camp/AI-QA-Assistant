"""Citation-preserving Markdown rendering from verified Claims only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import re

from agent.schemas.research import (
    ClaimVerificationStatus,
    CoverageResult,
    ResearchCitation,
    ResearchConflict,
    ResearchConflictAlternative,
    ResearchLimitation,
    ResearchReport,
    ResearchResultStatus,
    SourceManifest,
    VerifiedClaim,
    VerifiedEvidence,
)


class MarkdownReportRenderer:
    """Render existing verified objects; it has no Search or Read capability."""

    BOUNDARY_MARKERS = (
        "资料边界",
        "未包含",
        "无法确认",
        "尚未提供",
        "仍需确认",
        "not provided",
        "cannot confirm",
        "limitation",
    )

    def render(
        self,
        *,
        research_id: str,
        objective: str,
        claims: Iterable[VerifiedClaim],
        coverage: CoverageResult,
        evidence: Mapping[str, VerifiedEvidence] | Iterable[VerifiedEvidence] = (),
        manifest: SourceManifest | None = None,
        limitations: Iterable[str] = (),
        title: str | None = None,
        report_id: str | None = None,
        language: str | None = None,
    ) -> ResearchReport:
        # Repository insertion timestamps are operational metadata, not a
        # presentation order.  Recovery/replay can persist otherwise identical
        # entities in a different temporal order, so canonicalize the report
        # inputs before rendering.  This keeps fixed-fixture reports byte-for-
        # byte repeatable across fresh runs and process restarts.
        status_order = {
            ClaimVerificationStatus.SUPPORTED: 0,
            ClaimVerificationStatus.PARTIAL: 1,
            ClaimVerificationStatus.CONFLICTING: 2,
            ClaimVerificationStatus.UNSUPPORTED: 3,
        }
        claim_list = sorted(
            (claim for claim in claims if claim.research_id == research_id),
            key=lambda claim: (
                status_order[claim.status],
                self._is_boundary_claim(claim.claim_text),
                claim.claim_text,
                claim.claim_id,
            ),
        )
        evidence_map = (
            dict(evidence)
            if isinstance(evidence, Mapping)
            else {item.evidence_id: item for item in evidence}
        )
        source_metadata = {
            item.doc_id: item for item in (manifest.documents if manifest else [])
        }
        limitation_list = self._unique_text(limitations)
        answer_claims = [
            claim
            for claim in claim_list
            if claim.status in {
                ClaimVerificationStatus.SUPPORTED,
                ClaimVerificationStatus.PARTIAL,
            }
            and not self._is_boundary_claim(claim.claim_text)
        ]
        boundary_claims = [
            claim
            for claim in claim_list
            if claim.status in {
                ClaimVerificationStatus.SUPPORTED,
                ClaimVerificationStatus.PARTIAL,
            }
            and self._is_boundary_claim(claim.claim_text)
        ]
        conflict_claims = [
            claim
            for claim in claim_list
            if claim.status == ClaimVerificationStatus.CONFLICTING
        ]
        unsupported_claims = [
            claim
            for claim in claim_list
            if claim.status == ClaimVerificationStatus.UNSUPPORTED
        ]
        answer_groups = self._group_claims(answer_claims)
        boundary_groups = self._group_claims(boundary_claims)

        referenced_evidence: list[str] = []
        source_numbers: dict[tuple[str, str, str, str], int] = {}
        citation_by_evidence: dict[str, int] = {}
        sources: list[VerifiedEvidence] = []
        display_claims = answer_claims + conflict_claims + boundary_claims
        for claim in display_claims:
            for evidence_id in sorted(claim.evidence_ids):
                if evidence_id not in referenced_evidence:
                    referenced_evidence.append(evidence_id)
                item = evidence_map.get(evidence_id)
                if item is None:
                    continue
                key = (
                    item.doc_id,
                    item.document_version or "",
                    item.locator,
                    item.content_hash,
                )
                number = source_numbers.get(key)
                if number is None:
                    sources.append(item)
                    number = len(sources)
                    source_numbers[key] = number
                citation_by_evidence[evidence_id] = number

        lines = [f"# {title or objective}", "", "## 结论", ""]
        if answer_groups:
            for status, claim_text, evidence_ids in answer_groups:
                prefix = (
                    "现有资料部分支持："
                    if status == ClaimVerificationStatus.PARTIAL
                    else ""
                )
                lines.append(
                    f"- {prefix}{self._clean_display_text(claim_text)}"
                    f"{self._citation(evidence_ids, citation_by_evidence)}"
                )
        else:
            lines.append("- 现有资料不足以支持确定结论。")

        if conflict_claims:
            lines.extend(
                [
                    "",
                    "## 资料冲突",
                    "",
                    "以下来源对同一问题给出了不一致的信息：",
                    "",
                ]
            )
            conflict_evidence_ids = self._unique_ids(
                evidence_id
                for claim in conflict_claims
                for evidence_id in claim.evidence_ids
            )
            for evidence_id in conflict_evidence_ids:
                item = evidence_map.get(evidence_id)
                if item is None:
                    continue
                source_number = citation_by_evidence.get(evidence_id)
                version = f"（{item.document_version}）" if item.document_version else ""
                lines.append(
                    f"- **来源 {source_number}**{version}："
                    f"{self._clean_display_text(item.excerpt)}"
                    f"{self._citation([evidence_id], citation_by_evidence)}"
                )

        structured_limitations: list[ResearchLimitation] = []
        for status, claim_text, evidence_ids in boundary_groups:
            prefix = (
                "该项仅获得部分资料支持："
                if status == ClaimVerificationStatus.PARTIAL
                else ""
            )
            structured_limitations.append(
                ResearchLimitation(
                    code="source_boundary",
                    message=f"{prefix}{self._clean_display_text(claim_text)}",
                    evidence_ids=evidence_ids,
                )
            )
        structured_limitations.extend(
            ResearchLimitation(code="reported_limitation", message=item)
            for item in limitation_list
        )
        if any(
            claim.status == ClaimVerificationStatus.PARTIAL for claim in claim_list
        ):
            structured_limitations.append(
                ResearchLimitation(
                    code="partial_support",
                    message="部分结论仅获得有限证据支持，建议补充核验。",
                )
            )
        if unsupported_claims:
            structured_limitations.append(
                ResearchLimitation(
                    code="unsupported_claims_omitted",
                    message="部分候选结论因证据不足，未写入结论。",
                )
            )
        if coverage.missing:
            structured_limitations.append(
                ResearchLimitation(
                    code="required_coverage_missing",
                    message="部分研究要求尚未获得足够证据支持。",
                )
            )
        structured_limitations = self._unique_limitations(structured_limitations)
        pending_items = [
            f"{item.message}{self._citation(item.evidence_ids, citation_by_evidence)}"
            for item in structured_limitations
        ]
        if pending_items:
            lines.extend(["", "## 仍需确认", ""])
            lines.extend(f"- {item}" for item in pending_items)

        lines.extend(["", "## 来源", ""])
        if sources:
            for number, item in enumerate(sources, start=1):
                version = f" · {item.document_version}" if item.document_version else ""
                metadata = source_metadata.get(item.doc_id)
                display_title = metadata.title if metadata and metadata.title else item.doc_id
                display_link = (
                    f"[{display_title}]({metadata.source_url})"
                    if metadata and metadata.source_url
                    else f"**{display_title}**"
                )
                lines.append(
                    f"{number}. {display_link}{version} · {item.locator}"
                )
        else:
            lines.append("- 未记录可引用来源。")

        has_quality_gaps = bool(
            limitation_list
            or coverage.missing
            or any(
                claim.status != ClaimVerificationStatus.SUPPORTED
                for claim in claim_list
            )
        )
        result_status = (
            ResearchResultStatus.COMPLETE
            if coverage.sufficient and not has_quality_gaps
            else ResearchResultStatus.DEGRADED
        )
        citations = [
            self._build_citation(
                number,
                item,
                source_metadata.get(item.doc_id),
                [
                    evidence_id
                    for evidence_id, citation_number in citation_by_evidence.items()
                    if citation_number == number
                ],
            )
            for number, item in enumerate(sources, start=1)
        ]
        conflicts = self._build_conflicts(
            conflict_claims,
            evidence_map,
            citation_by_evidence,
            source_metadata,
        )
        return ResearchReport(
            report_id=report_id or f"report-{research_id}",
            research_id=research_id,
            markdown="\n".join(lines).strip() + "\n",
            result_status=result_status,
            claim_ids=[claim.claim_id for claim in claim_list],
            evidence_ids=referenced_evidence,
            citations=citations,
            conflicts=conflicts,
            limitations=structured_limitations,
        )

    @staticmethod
    def _build_citation(number, evidence, metadata, evidence_ids) -> ResearchCitation:
        return ResearchCitation(
            number=number,
            evidence_id=evidence.evidence_id,
            evidence_ids=evidence_ids,
            doc_id=evidence.doc_id,
            title=(metadata.title if metadata and metadata.title else evidence.doc_id),
            source_url=(metadata.source_url if metadata else None),
            source_type=(metadata.source_type if metadata else "local_document"),
            authority=(metadata.authority if metadata else "internal"),
            authority_rank=(metadata.authority_rank if metadata else 0),
            document_version=evidence.document_version,
            effective_at=(metadata.effective_at if metadata else None),
            updated_at=(metadata.updated_at if metadata else None),
            locator=evidence.locator,
            excerpt=evidence.excerpt,
            content_hash=evidence.content_hash,
        )

    @classmethod
    def _build_conflicts(
        cls,
        claims,
        evidence_map,
        citation_by_evidence,
        source_metadata,
    ) -> list[ResearchConflict]:
        output: list[ResearchConflict] = []
        for claim in claims:
            alternatives: list[ResearchConflictAlternative] = []
            selected = []
            for evidence_id in cls._unique_ids(claim.evidence_ids):
                item = evidence_map.get(evidence_id)
                number = citation_by_evidence.get(evidence_id)
                if item is None or number is None:
                    continue
                metadata = source_metadata.get(item.doc_id)
                selected.append((item, metadata))
                alternatives.append(
                    ResearchConflictAlternative(
                        citation_number=number,
                        evidence_id=evidence_id,
                        source_title=(
                            metadata.title
                            if metadata and metadata.title
                            else item.doc_id
                        ),
                        value_summary=cls._clean_display_text(item.excerpt),
                        document_version=item.document_version,
                        effective_at=(metadata.effective_at if metadata else None),
                        updated_at=(metadata.updated_at if metadata else None),
                        authority=(metadata.authority if metadata else "internal"),
                        authority_rank=(metadata.authority_rank if metadata else 0),
                    )
                )
            if len(alternatives) < 2:
                continue
            versions = {
                item.document_version for item, _ in selected if item.document_version
            }
            number_sets = {
                tuple(re.findall(r"\d+(?:\.\d+)?", item.excerpt))
                for item, _ in selected
            }
            conflict_type = (
                "version"
                if len(versions) > 1
                else "numeric"
                if len(number_sets) > 1
                else "source"
            )
            source_names = "与".join(
                f"《{item.source_title}》" for item in alternatives[:2]
            )
            type_label = {"version": "版本", "numeric": "数值", "source": "表述"}[
                conflict_type
            ]
            ranked = sorted(
                (
                    (metadata.authority_rank if metadata else 0, item, metadata)
                    for item, metadata in selected
                ),
                key=lambda entry: entry[0],
                reverse=True,
            )
            resolved = len(ranked) > 1 and ranked[0][0] > ranked[1][0]
            preferred = ranked[0][2] if resolved else None
            resolution = (
                f"按资料权威级别，优先参考《{preferred.title}》。"
                if preferred is not None
                else ""
            )
            output.append(
                ResearchConflict(
                    conflict_id=(
                        "conflict-"
                        + hashlib.sha256(claim.claim_id.encode("utf-8")).hexdigest()[:16]
                    ),
                    subject=f"{source_names}的{type_label}差异",
                    conflict_type=conflict_type,
                    summary="多个来源对同一研究问题给出了不一致的信息。",
                    alternatives=alternatives,
                    resolution_status=(
                        "resolved_by_authority" if resolved else "unresolved"
                    ),
                    resolution=resolution,
                )
            )
        return output

    @staticmethod
    def _citation(
        evidence_ids: Iterable[str],
        citation_by_evidence: Mapping[str, int],
    ) -> str:
        numbers = sorted(
            {
                citation_by_evidence[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in citation_by_evidence
            }
        )
        return " " + " ".join(f"[{number}]" for number in numbers) if numbers else ""

    @classmethod
    def _is_boundary_claim(cls, text: str) -> bool:
        normalized = text.casefold()
        return any(marker.casefold() in normalized for marker in cls.BOUNDARY_MARKERS)

    @staticmethod
    def _unique_ids(values: Iterable[str]) -> list[str]:
        output: list[str] = []
        for value in values:
            if value not in output:
                output.append(value)
        return output

    @staticmethod
    def _unique_limitations(values: Iterable[ResearchLimitation]) -> list[ResearchLimitation]:
        output: list[ResearchLimitation] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for value in values:
            key = (value.code, value.message, tuple(value.evidence_ids))
            if key not in seen:
                seen.add(key)
                output.append(value)
        return output

    @staticmethod
    def _group_claims(
        claims: Iterable[VerifiedClaim],
    ) -> list[tuple[ClaimVerificationStatus, str, list[str]]]:
        grouped: dict[tuple[ClaimVerificationStatus, str], list[str]] = {}
        for claim in claims:
            key = (claim.status, claim.claim_text)
            evidence_ids = grouped.setdefault(key, [])
            for evidence_id in claim.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        return [
            (status, claim_text, evidence_ids)
            for (status, claim_text), evidence_ids in grouped.items()
        ]

    @staticmethod
    def _clean_display_text(text: str) -> str:
        cleaned = " ".join(text.strip().split())
        for marker in ("案例结论：", "资料边界：", "FAQ页面答复："):
            marker_index = cleaned.find(marker)
            if 0 <= marker_index < 80:
                cleaned = cleaned[marker_index + len(marker):].strip()
        return cleaned

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
