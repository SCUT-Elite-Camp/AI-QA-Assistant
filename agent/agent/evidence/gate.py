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
        if policy.evidence_policy == "none":
            return self._result(
                accepted=True,
                evidence=[],
                reason="evidence_not_required",
                policy=policy,
                retrieval_attempt=retrieval_attempt,
            )

        if not 1 <= retrieval_attempt <= policy.max_retrieval_attempts:
            raise ValueError(
                "retrieval_attempt must be within the policy retrieval budget"
            )

        eligible = self._filter_and_deduplicate(evidence)

        if policy.evidence_policy in {"single_fact", "document_identity"}:
            accepted = bool(eligible)
            return self._result(
                accepted=accepted,
                evidence=eligible if accepted else [],
                reason="evidence_accepted" if accepted else "no_valid_evidence",
                policy=policy,
                retrieval_attempt=retrieval_attempt,
            )

        if policy.evidence_policy == "topic_coverage":
            accepted = len(eligible) >= 2
            return self._result(
                accepted=accepted,
                evidence=eligible if accepted else [],
                reason=(
                    "topic_coverage_sufficient"
                    if accepted
                    else "topic_coverage_insufficient"
                ),
                policy=policy,
                retrieval_attempt=retrieval_attempt,
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
                missing_targets=missing,
                policy=policy,
                retrieval_attempt=retrieval_attempt,
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
        missing_targets: list[str] | None = None,
    ) -> EvidenceGateResult:
        return EvidenceGateResult(
            accepted=accepted,
            evidence=evidence,
            reason=reason,
            missing_targets=missing_targets or [],
            should_retry=(
                not accepted
                # CorrectiveRetrievalPlanner deliberately owns only the
                # bounded first -> second search fallback. Later attempts are
                # normal multi-tool/document-page reads and must not trigger
                # another automatic corrective search.
                and retrieval_attempt == 1
                and policy.max_retrieval_attempts >= 2
            ),
            retrieval_attempt=retrieval_attempt,
        )
