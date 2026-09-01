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
        if retrieval_attempt not in {1, 2}:
            raise ValueError("retrieval_attempt must be one or two")

        eligible = self._filter_and_deduplicate(evidence)
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
                if not self._has_retrieval_for(target, eligible)
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

    def _filter_and_deduplicate(
        self,
        evidence: list[Evidence],
    ) -> list[Evidence]:
        best_by_chunk: dict[tuple[str, str], Evidence] = {}
        for item in evidence:
            if item.score < self.min_score:
                continue
            key = (item.doc_id, item.chunk_id)
            current = best_by_chunk.get(key)
            if current is None or item.score > current.score:
                best_by_chunk[key] = item
        return sorted(
            best_by_chunk.values(),
            key=lambda item: item.score,
            reverse=True,
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
        return any(
            item.retrieval_query.strip().casefold() == normalized_target
            for item in evidence
        )

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
