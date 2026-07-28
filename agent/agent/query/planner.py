import json
import logging
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
            return QueryEnrichment(reason="query_planning_skipped")

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
            return QueryEnrichment(reason="query_planning_failed")

        return QueryEnrichment(
            sub_queries=result.sub_queries,
            filters=self._supported_filters(result.filters),
            reason=result.reason,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Plan retrieval for an enterprise knowledge Agent. "
            "Return JSON only with keys sub_queries, filters, and reason. "
            "For comparison, create one self-contained sub-query per comparison "
            "target. For other intents, use sub_queries only when decomposition "
            "materially improves retrieval. Return at most four sub-queries. "
            "Extract filters only when explicitly stated by the user. Supported "
            "filter keys are doc_id, doc_ids, space, and doc_type. Do not infer "
            "unstated facts or add any other filter key. Example shape: "
            '{"sub_queries":[],"filters":{},"reason":"not needed"}'
        )

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
