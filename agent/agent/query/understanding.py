from copy import deepcopy
import logging
from typing import Any

from agent.config.settings import settings
from agent.query.clarifier import Clarifier
from agent.query.clarification_gate import ClarificationGate
from agent.query.intent_classifier import IntentClassifier
from agent.query.hybrid_intent import HybridIntentRouter
from agent.query.planner import QueryPlanner
from agent.query.preparation import QueryPreparationAnalyzer
from agent.query.rewriter import QueryRewriter
from agent.query.unified import UnifiedQueryAnalyzer
from agent.schemas.query_plan import QueryIntent, QueryPlan


class QueryUnderstanding:
    """Compose CP2 query components into the frozen QueryPlan contract."""

    RETRIEVAL_INTENTS = frozenset(
        {
            QueryIntent.KNOWLEDGE_QA,
            QueryIntent.DOCUMENT_SEARCH,
            QueryIntent.SUMMARIZATION,
            QueryIntent.COMPARISON,
        }
    )

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        clarifier: Clarifier | None = None,
        query_rewriter: QueryRewriter | None = None,
        query_planner: QueryPlanner | None = None,
        unified_analyzer: UnifiedQueryAnalyzer | None = None,
        unified_enabled: bool | None = None,
        clarification_gate: ClarificationGate | None = None,
        query_preparation: QueryPreparationAnalyzer | None = None,
        cascaded_enabled: bool | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier or HybridIntentRouter()
        self.clarifier = clarifier or Clarifier()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.query_planner = query_planner or QueryPlanner()
        self.unified_analyzer = unified_analyzer or UnifiedQueryAnalyzer()
        self.unified_enabled = (
            settings.UNIFIED_QUERY_UNDERSTANDING_ENABLED
            if unified_enabled is None
            else unified_enabled
        )
        self.clarification_gate = clarification_gate or ClarificationGate(
            self.clarifier
        )
        self.query_preparation = query_preparation or QueryPreparationAnalyzer()
        self.cascaded_enabled = (
            settings.CASCADED_QUERY_UNDERSTANDING_ENABLED
            if cascaded_enabled is None
            else cascaded_enabled
        )
        self.logger = logging.getLogger("agent-layer.query")

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

        if self.cascaded_enabled:
            return self._analyze_cascaded(
                query,
                readonly_history,
                plan_filters,
            )

        if self.unified_enabled:
            try:
                unified = self.unified_analyzer.analyze(query, readonly_history)
                unified_filters = deepcopy(unified.filters)
                unified_filters.update(plan_filters)
                return QueryPlan(
                    original_query=query,
                    standalone_query=unified.standalone_query,
                    intent=unified.intent,
                    intent_confidence=unified.confidence,
                    is_follow_up=unified.is_follow_up,
                    is_clarification_reply=unified.is_clarification_reply,
                    needs_clarification=unified.needs_clarification,
                    clarification_question=unified.clarification_question,
                    ambiguity_reason=unified.ambiguity_reason,
                    sub_queries=unified.sub_queries,
                    filters=unified_filters,
                )
            except Exception as exc:
                self.logger.warning(
                    "[UNIFIED_QUERY_UNDERSTANDING] action=fallback error=%s query=%s",
                    str(exc),
                    query.strip(),
                )

        intent = self.intent_classifier.classify(query, readonly_history)
        clarification = self.clarifier.evaluate(query, readonly_history)

        if clarification.needs_clarification:
            standalone_query = query.strip()
            sub_queries: list[str] = []
        else:
            rewrite = self.query_rewriter.rewrite(query, readonly_history)
            standalone_query = rewrite.rewritten_query
            enrichment = self.query_planner.enrich(
                standalone_query,
                intent.intent,
            )
            sub_queries = enrichment.sub_queries
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
        )

    def _analyze_cascaded(
        self,
        query: str,
        history: list[dict[str, Any]],
        plan_filters: dict[str, Any],
    ) -> QueryPlan:
        intent = self.intent_classifier.classify(query, history)
        if intent.intent not in self.RETRIEVAL_INTENTS:
            return QueryPlan(
                original_query=query,
                standalone_query=query.strip(),
                intent=intent.intent,
                intent_confidence=intent.confidence,
                is_follow_up=intent.is_follow_up,
                is_clarification_reply=intent.is_clarification_reply,
                filters=plan_filters,
            )

        clarification = self.clarification_gate.evaluate(query, history)
        if clarification.needs_clarification:
            return QueryPlan(
                original_query=query,
                standalone_query=query.strip(),
                intent=intent.intent,
                intent_confidence=intent.confidence,
                is_follow_up=intent.is_follow_up,
                is_clarification_reply=intent.is_clarification_reply,
                needs_clarification=True,
                clarification_question=clarification.question,
                ambiguity_reason=clarification.reason,
                filters=plan_filters,
            )

        try:
            prepared = self.query_preparation.prepare(query, history, intent.intent)
            semantic_filters = deepcopy(prepared.filters)
            semantic_filters.update(plan_filters)
            standalone_query = prepared.standalone_query
            sub_queries = prepared.sub_queries
            plan_filters = semantic_filters
        except Exception as exc:
            self.logger.warning(
                "[QUERY_PREPARATION] action=fallback error=%s query=%s",
                str(exc),
                query.strip(),
            )
            rewrite = self.query_rewriter.rewrite(query, history)
            standalone_query = rewrite.rewritten_query
            enrichment = self.query_planner.enrich(
                standalone_query,
                intent.intent,
            )
            sub_queries = enrichment.sub_queries
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
            needs_clarification=False,
            clarification_question="",
            ambiguity_reason=clarification.reason,
            sub_queries=sub_queries,
            filters=plan_filters,
        )
