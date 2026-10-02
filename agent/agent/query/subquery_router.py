import logging
import re

from agent.policy import IntentPolicyRouter
from agent.query.intent_classifier import IntentClassifier
from agent.query.hybrid_intent import HybridIntentRouter
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.schemas.subquery_routing import SubQueryRoute, SubQueryRoutingResult


class SubQueryRouter:
    """Classify and policy-route independently executable sub-queries."""

    def __init__(
        self,
        intent_classifier: IntentClassifier,
        policy_router: IntentPolicyRouter,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier
        self.policy_router = policy_router
        self.logger = logger or logging.getLogger("agent-layer.query")

    def route(self, query_plan: QueryPlan) -> SubQueryRoutingResult:
        sub_queries = tuple(dict.fromkeys(query_plan.sub_queries))
        if len(sub_queries) < 2:
            return SubQueryRoutingResult(is_complex=False)

        if isinstance(self.intent_classifier, HybridIntentRouter):
            classifications = self.intent_classifier.classify_local_batch(
                list(sub_queries),
                default_intent=query_plan.intent,
            )
        else:
            classifications = [
                self.intent_classifier.classify(sub_query, [])
                for sub_query in sub_queries
            ]

        hints = query_plan._subquery_intent_hints
        resolved = []
        uncertain_indexes: list[int] = []
        for index, (sub_query, local_result) in enumerate(
            zip(sub_queries, classifications)
        ):
            action_intent = self._action_intent(sub_query)
            hint = hints.get(sub_query)
            if action_intent is not None:
                resolved.append(local_result.model_copy(update={
                    "intent": action_intent,
                    "confidence": 1.0,
                    "reason": "subquery_action_rule",
                }))
            elif hint is not None and (
                local_result.reason == "local_only_parent_intent_fallback"
                or hint == local_result.intent
            ):
                resolved.append(local_result.model_copy(update={
                    "intent": hint,
                    "confidence": max(local_result.confidence, 0.8),
                    "reason": "planner_hint_validated",
                }))
            else:
                resolved.append(local_result)
                if (
                    hint is None
                    and local_result.reason == "local_only_parent_intent_fallback"
                ) or (hint is not None and hint != local_result.intent):
                    uncertain_indexes.append(index)

        if uncertain_indexes and isinstance(self.intent_classifier, HybridIntentRouter):
            uncertain_queries = [sub_queries[index] for index in uncertain_indexes]
            batch_results = self.intent_classifier.fallback.classify_batch(
                uncertain_queries
            )
            for index, result in zip(uncertain_indexes, batch_results):
                if result.confidence > 0:
                    resolved[index] = result
                elif hints.get(sub_queries[index]) is not None:
                    resolved[index] = resolved[index].model_copy(update={
                        "intent": hints[sub_queries[index]],
                        "confidence": 0.6,
                        "reason": "planner_hint_after_batch_failure",
                    })
        classifications = resolved

        routes: list[SubQueryRoute] = []
        for sub_query, classified in zip(sub_queries, classifications):
            child_plan = QueryPlan(
                original_query=sub_query,
                standalone_query=sub_query,
                intent=classified.intent,
                intent_confidence=classified.confidence,
            )
            policy = self.policy_router.route(child_plan)
            routes.append(
                SubQueryRoute(
                    query=sub_query,
                    intent=classified.intent,
                    confidence=classified.confidence,
                    policy=policy,
                )
            )
            self.logger.info(
                "[SUBQUERY_ROUTING] intent=%s confidence=%.3f tools=%s query=%s",
                classified.intent.value,
                classified.confidence,
                ",".join(policy.candidate_tools) or "none",
                sub_query,
            )
        return SubQueryRoutingResult(is_complex=True, routes=tuple(routes))

    @staticmethod
    def _action_intent(query: str) -> QueryIntent | None:
        normalized = query.strip().lower()
        if re.search(r"\b(?:compare|contrast|difference|differences|versus|vs\.?)\b", normalized):
            return QueryIntent.COMPARISON
        if re.search(r"\b(?:summarize|summary|overview|recap)\b", normalized):
            return QueryIntent.SUMMARIZATION
        if re.search(r"\b(?:find|locate|list|search)\b.*\b(?:document|documents|file|files|contract)\b", normalized):
            return QueryIntent.DOCUMENT_SEARCH
        return None
