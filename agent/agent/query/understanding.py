from copy import deepcopy
from typing import Any

from agent.query.clarifier import Clarifier
from agent.query.intent_classifier import IntentClassifier
from agent.query.planner import QueryPlanner
from agent.query.rewriter import QueryRewriter
from agent.query.source_intent import heuristic_source_intent
from agent.schemas.query_plan import QueryPlan


class QueryUnderstanding:
    """Compose CP2 query components into the frozen QueryPlan contract."""

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        clarifier: Clarifier | None = None,
        query_rewriter: QueryRewriter | None = None,
        query_planner: QueryPlanner | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.clarifier = clarifier or Clarifier()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.query_planner = query_planner or QueryPlanner()

    def analyze(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        *,
        filters: dict[str, Any] | None = None,
    ) -> QueryPlan:
        """Return one validated QueryPlan without mutating Memory or inputs."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        readonly_history = deepcopy(history or [])
        plan_filters = deepcopy(filters or {})

        intent = self.intent_classifier.classify(query, readonly_history)
        clarification = self.clarifier.evaluate(query, readonly_history)

        if clarification.needs_clarification:
            standalone_query = query.strip()
            sub_queries: list[str] = []
            source_intent = heuristic_source_intent(
                standalone_query,
                enterprise_default=False,
            )
        else:
            rewrite = self.query_rewriter.rewrite(query, readonly_history)
            standalone_query = rewrite.rewritten_query
            enrichment = self.query_planner.enrich(
                standalone_query,
                intent.intent,
            )
            sub_queries = enrichment.sub_queries
            source_intent = enrichment.source_intent
            semantic_filters = enrichment.filters
            semantic_filters.update(plan_filters)
            plan_filters = semantic_filters

        return QueryPlan(
            original_query=query,
            standalone_query=standalone_query,
            intent=intent.intent,
            intent_confidence=intent.confidence,
            is_follow_up=intent.is_follow_up,
            is_clarification_reply=intent.is_clarification_reply,
            needs_clarification=clarification.needs_clarification,
            clarification_question=clarification.question,
            ambiguity_reason=clarification.reason,
            sub_queries=sub_queries,
            filters=plan_filters,
            source_intent=source_intent,
        )
