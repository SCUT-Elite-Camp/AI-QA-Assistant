"""Append bounded Wiki Evidence without reranking accepted Direct Evidence."""

from dataclasses import dataclass

from agent.evidence.gate import EvidenceGate
from agent.schemas.tool_execution import Evidence


@dataclass(frozen=True)
class WikiEvidenceSupplementResult:
    evidence: list[Evidence]
    wiki_selected: int
    wiki_duplicates_skipped: int


class WikiEvidenceSupplementer:
    """Filter Wiki candidates and append unique items to Direct Evidence."""

    def __init__(
        self,
        *,
        evidence_gate: EvidenceGate,
        wiki_top_k: int,
    ) -> None:
        if not 0 <= wiki_top_k <= 10:
            raise ValueError("wiki_top_k must be between zero and ten")
        self.evidence_gate = evidence_gate
        self.wiki_top_k = wiki_top_k

    def supplement(
        self,
        direct_evidence: list[Evidence],
        wiki_candidates: list[Evidence],
    ) -> WikiEvidenceSupplementResult:
        if self.wiki_top_k == 0:
            return WikiEvidenceSupplementResult(
                evidence=list(direct_evidence),
                wiki_selected=0,
                wiki_duplicates_skipped=0,
            )

        wiki = self.evidence_gate.select_eligible(
            wiki_candidates,
            require_version_id=True,
        )
        eligible_direct = self.evidence_gate.select_eligible(direct_evidence)
        seen = {
            self.evidence_gate.evidence_key(item)
            for item in eligible_direct
        }
        selected: list[Evidence] = []
        duplicate_count = 0
        for item in wiki:
            key = self.evidence_gate.evidence_key(item)
            if key in seen or any(
                self._matches_incomplete_direct(direct, item)
                for direct in eligible_direct
            ):
                duplicate_count += 1
                continue
            seen.add(key)
            selected.append(item)
            if len(selected) >= self.wiki_top_k:
                break

        return WikiEvidenceSupplementResult(
            evidence=[*direct_evidence, *selected],
            wiki_selected=len(selected),
            wiki_duplicates_skipped=duplicate_count,
        )

    @staticmethod
    def _matches_incomplete_direct(direct: Evidence, wiki: Evidence) -> bool:
        """Match the same chunk when legacy Direct metadata is incomplete."""

        direct_document = (direct.document_id or direct.doc_id).strip()
        wiki_document = (wiki.document_id or wiki.doc_id).strip()
        if direct_document != wiki_document or direct.chunk_id != wiki.chunk_id:
            return False

        direct_scope = (direct.source_scope or "").strip()
        wiki_scope = (wiki.source_scope or "").strip()
        if direct_scope and wiki_scope and direct_scope != wiki_scope:
            return False

        direct_version = (direct.version_id or "").strip()
        wiki_version = (wiki.version_id or "").strip()
        return not direct_version or not wiki_version or direct_version == wiki_version
