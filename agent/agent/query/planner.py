import json
import logging
import re
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.schemas import QueryEnrichment
from agent.schemas.query_plan import QueryIntent


class QueryPlanner:
    """Generate bounded retrieval sub-queries and supported semantic filters."""

    FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})
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
        llm: BaseLLM | None = None,
        *,
        enabled: bool | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.enabled = (
            settings.QUERY_UNDERSTANDING_ENABLED
            if enabled is None
            else enabled
        )
        self.logger = logger or logging.getLogger("agent-layer.query")

    def enrich(
        self,
        standalone_query: str,
        intent: QueryIntent,
    ) -> QueryEnrichment:
        """Return optional retrieval planning data with a safe empty fallback."""
        query = standalone_query.strip()
        if not query or not self.enabled or intent not in self.RETRIEVAL_INTENTS:
            navigation_mode = self._heuristic_navigation_mode(query, intent)
            return QueryEnrichment(
                navigation_mode=navigation_mode,
                needs_structure=navigation_mode != "direct",
                needs_version_reasoning=self._needs_version_reasoning(query),
                reason="query_planning_skipped",
            )
        if intent == QueryIntent.KNOWLEDGE_QA and self._is_simple_single_target(query):
            self.logger.info(
                "[QUERY_PLANNING] action=fast_path reason=simple_single_target query=%s",
                query,
            )
            return QueryEnrichment(reason="simple_knowledge_qa_fast_path")

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "intent": intent.value},
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            response = self.llm.chat(messages)
            result = self._parse_response(response)
        except Exception as exc:
            self.logger.warning(
                "[QUERY_PLANNING] action=fallback error=%s query=%s",
                exc.__class__.__name__,
                query,
            )
            navigation_mode = self._heuristic_navigation_mode(query, intent)
            return QueryEnrichment(
                navigation_mode=navigation_mode,
                needs_structure=navigation_mode != "direct",
                needs_version_reasoning=self._needs_version_reasoning(query),
                reason="query_planning_failed",
            )

        return QueryEnrichment(
            sub_queries=result.sub_queries,
            filters=self._supported_filters(result.filters),
            navigation_mode=result.navigation_mode,
            scope=result.scope,
            needs_structure=result.needs_structure,
            needs_knowledge=False,
            needs_version_reasoning=result.needs_version_reasoning,
            reason=result.reason,
        )

    @staticmethod
    def _is_simple_single_target(query: str) -> bool:
        """Return true only when decomposition is unlikely to improve retrieval."""

        if len(query) > 120 or query.count("?") + query.count("？") > 1:
            return False
        complex_patterns = (
            r"\bcompare\b|\bversus\b|\bvs\.?\b|\bdifference\b",
            r"\band\b.*\b(?:why|how|what|which|where|when)\b",
            r"比较|对比|区别|差异|分别|各自|两者|以及|同时|并且",
            r"[，,；;].*(?:为什么|如何|哪些|什么|是否|怎么)",
        )
        return not any(
            re.search(pattern, query, flags=re.IGNORECASE)
            for pattern in complex_patterns
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Plan retrieval for an enterprise knowledge Agent. "
            "Return JSON only with keys sub_queries, filters, navigation_mode, scope, "
            "needs_structure, needs_knowledge, needs_version_reasoning, and reason. "
            "Use direct for exact facts, hierarchical for long cross-section or version "
            "reasoning, and hybrid for ambiguous, cross-document, or complex questions. "
            "scope is single_doc, multi_doc, or kb. needs_knowledge must be false. "
            "For comparison, create one self-contained sub-query per comparison "
            "target. For other intents, use sub_queries only when decomposition "
            "materially improves retrieval. Return at most four sub-queries. "
            "Extract filters only when explicitly stated by the user. Supported "
            "filter keys are doc_id, doc_ids, space, and doc_type. Do not infer "
            "unstated facts or add any other filter key. Example shape: "
            '{"sub_queries":[],"filters":{},"navigation_mode":"direct",'
            '"scope":"kb","needs_structure":false,"needs_knowledge":false,'
            '"needs_version_reasoning":false,"reason":"not needed"}'
        )

    @staticmethod
    def _needs_version_reasoning(query: str) -> bool:
        lowered = query.casefold()
        return any(token in lowered for token in (
            "版本", "修订", "变更", "变化", "历史", "previous version",
            "latest version", "revision", "changed between",
        ))

    @classmethod
    def _heuristic_navigation_mode(cls, query: str, intent: QueryIntent) -> str:
        lowered = query.casefold()
        complex_tokens = (
            "跨章节", "跨文档", "综合", "比较", "演变", "版本", "全文",
            "across sections", "across documents", "compare", "summarize",
        )
        if intent in {QueryIntent.COMPARISON, QueryIntent.SUMMARIZATION}:
            return "hybrid"
        if any(token in lowered for token in complex_tokens):
            return "hybrid"
        return "direct"

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> QueryEnrichment:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")
        text = content.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(text)
            return QueryEnrichment.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("LLM query planning response is invalid") from exc

    @classmethod
    def _supported_filters(cls, filters: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(
            {
                key: value
                for key, value in filters.items()
                if key in cls.FILTER_KEYS and value not in (None, "", [])
            }
        )
