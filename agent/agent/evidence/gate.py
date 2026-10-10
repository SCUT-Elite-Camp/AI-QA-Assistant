from agent.config.settings import settings
from agent.evidence.schemas import EvidenceGateResult
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence


class EvidenceGate:
    """Apply intent-specific, deterministic evidence acceptance rules."""

    def __init__(self, *, min_score: float | None = None) -> None:
        self.min_score = (
            settings.MIN_RETRIEVAL_SCORE if min_score is None else min_score
        )
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score must be between zero and one")

    def evaluate(
        self,
        query_plan: QueryPlan,
        policy: IntentPolicy,
        evidence: list[Evidence],
        *,
        retrieval_attempt: int,
    ) -> EvidenceGateResult:
        if not 1 <= retrieval_attempt <= 5:
            raise ValueError("retrieval_attempt must be between one and five")

        # Document discovery summaries establish identity, not factual support.
        # Require a chunk read/search before answering questions about contents.
        supporting = evidence if policy.evidence_policy == "document_identity" else [
            item for item in evidence if item.chunk_id != f"{item.doc_id}::document"
        ]
        eligible = self.select_eligible(supporting)
        covered = self._covered_targets(eligible)
        counts = {
            "candidate_evidence_count": len(evidence),
            "eligible_evidence_count": len(eligible),
            "rejected_evidence_count": max(0, len(evidence) - len(eligible)),
        }

        if policy.evidence_policy == "none":
            return self._result(
                accepted=True,
                evidence=[],
                reason="evidence_not_required",
                policy=policy,
                retrieval_attempt=retrieval_attempt,
                **counts,
            )

        if policy.evidence_policy in {"single_fact", "document_identity"}:
            accepted = bool(eligible)
            missing = [] if accepted else self._missing_targets(query_plan, covered)
            return self._result(
                accepted=accepted,
                evidence=eligible if accepted else [],
                reason="evidence_accepted" if accepted else "no_valid_evidence",
                covered_targets=covered,
                missing_targets=missing,
                policy=policy,
                retrieval_attempt=retrieval_attempt,
                **counts,
            )

        if policy.evidence_policy == "topic_coverage":
            accepted = len(eligible) >= 2
            missing = [] if accepted else self._missing_targets(query_plan, covered)
            return self._result(
                accepted=accepted,
                evidence=eligible if accepted else [],
                reason=(
                    "topic_coverage_sufficient"
                    if accepted
                    else "topic_coverage_insufficient"
                ),
                covered_targets=covered,
                missing_targets=missing,
                policy=policy,
                retrieval_attempt=retrieval_attempt,
                **counts,
            )

        if policy.evidence_policy == "bilateral_coverage":
            targets = self._comparison_targets(query_plan)
            missing = [
                target
                for target in targets
                # A section may be retrieved for both comparison targets.
                # Deduplicating first loses its second query provenance.
                if not self._has_retrieval_for(
                    target, [item for item in supporting if item.score >= self.min_score]
                )
            ]
            accepted = bool(targets) and not missing
            reason = (
                "comparison_coverage_sufficient"
                if accepted
                else (
                    "comparison_sub_queries_missing"
                    if not targets
                    else "comparison_coverage_insufficient"
                )
            )
            return self._result(
                accepted=accepted,
                evidence=eligible if accepted else [],
                reason=reason,
                covered_targets=covered,
                missing_targets=missing,
                policy=policy,
                retrieval_attempt=retrieval_attempt,
                **counts,
            )

        raise ValueError(f"unsupported evidence policy: {policy.evidence_policy}")

    def select_eligible(
        self,
        evidence: list[Evidence],
        *,
        require_version_id: bool = False,
    ) -> list[Evidence]:
        """Apply the canonical score, identity, and deduplication rules."""

        best_by_chunk: dict[tuple[str, str, str, str], Evidence] = {}
        for item in evidence:
            if item.score < self.min_score:
                continue
            if require_version_id and not (item.version_id or "").strip():
                continue
            key = self.evidence_key(item)
            current = best_by_chunk.get(key)
            if current is None or item.score > current.score:
                best_by_chunk[key] = item
        return sorted(
            best_by_chunk.values(),
            key=lambda item: item.score,
            reverse=True,
        )

    @staticmethod
    def evidence_key(item: Evidence) -> tuple[str, str, str, str]:
        """Return the stable identity used across candidate pools."""

        return (
            (item.source_scope or "").strip(),
            (item.document_id or item.doc_id).strip(),
            (item.version_id or "").strip(),
            item.chunk_id.strip(),
        )

    @staticmethod
    def _comparison_targets(query_plan: QueryPlan) -> list[str]:
        return [query.strip() for query in query_plan.sub_queries if query.strip()]

    @staticmethod
    def _covered_targets(evidence: list[Evidence]) -> list[str]:
        return list(dict.fromkeys(item.retrieval_query for item in evidence))

    @staticmethod
    def _missing_targets(query_plan: QueryPlan, covered: list[str]) -> list[str]:
        targets = [query.strip() for query in query_plan.sub_queries if query.strip()]
        if not targets:
            return [query_plan.standalone_query]
        covered_normalized = {value.casefold() for value in covered}
        missing = [target for target in targets if target.casefold() not in covered_normalized]
        return missing or [query_plan.standalone_query]

    @staticmethod
    def _has_retrieval_for(target: str, evidence: list[Evidence]) -> bool:
        normalized_target = target.casefold()
        if any(
            item.retrieval_query.strip().casefold() == normalized_target
            for item in evidence
        ):
            return True
        # A guarded original read uses its doc_id as retrieval_query. Match a
        # named dated meeting by its recorded title identity, not by pretending
        # it was a hit for a query that returned no passages. This proves source
        # coverage only; answer generation still verifies the requested facts.
        import re
        if not re.search(r'\b(?:meeting|minutes)\b', target, re.I):
            return False
        months = 'January February March April May June July August September October November December'.split()
        named = re.search(r'\b(' + '|'.join(months) + r')\s+(\d{1,2})\b', target, re.I)
        if not named:
            return False
        month = next(i + 1 for i, name in enumerate(months) if name.casefold() == named.group(1).casefold())
        day = int(named.group(2))
        year = re.search(r'\b(\d{4})\b', target)
        for item in evidence:
            if item.read_status != 'original_excerpt_loaded' or not re.search(r'\b(?:meeting|minutes)\b', item.title.replace('+', ' '), re.I):
                continue
            date = re.search(r'\b(\d{4})\D+(\d{2})\D+(\d{2})\b', item.title.replace('+', ' '))
            if date and int(date.group(2)) == month and int(date.group(3)) == day and (not year or date.group(1) == year.group(1)):
                return True
        return False

    @staticmethod
    def _result(
        *,
        accepted: bool,
        evidence: list[Evidence],
        reason: str,
        policy: IntentPolicy,
        retrieval_attempt: int,
        covered_targets: list[str] | None = None,
        missing_targets: list[str] | None = None,
        candidate_evidence_count: int = 0,
        eligible_evidence_count: int = 0,
        rejected_evidence_count: int = 0,
    ) -> EvidenceGateResult:
        return EvidenceGateResult(
            accepted=accepted,
            evidence=evidence,
            reason=reason,
            covered_targets=covered_targets or [],
            missing_targets=missing_targets or [],
            candidate_evidence_count=candidate_evidence_count,
            eligible_evidence_count=eligible_evidence_count,
            rejected_evidence_count=rejected_evidence_count,
            should_retry=(
                not accepted
                and retrieval_attempt < policy.max_retrieval_attempts
            ),
            retrieval_attempt=retrieval_attempt,
        )
