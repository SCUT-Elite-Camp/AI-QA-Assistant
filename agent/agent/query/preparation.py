import json
import logging
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.intent_classifier import IntentClassifier
from agent.query.schemas import QueryPreparationResult
from agent.schemas.query_plan import QueryIntent


class QueryPreparationAnalyzer:
    """Combine reference resolution, rewrite, and retrieval planning."""

    FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})

    def __init__(
        self,
        llm: BaseLLM | None = None,
        *,
        fallback_llm: BaseLLM | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.fallback_llm = fallback_llm
        self.logger = logger or logging.getLogger("agent-layer.query")
        self.primary_attempts = 0
        self.fallback_attempts = 0

    def prepare(
        self,
        query: str,
        history: list[dict[str, Any]],
        intent: QueryIntent,
    ) -> QueryPreparationResult:
        messages = [
            {"role": "system", "content": self._system_prompt(intent)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "intent": intent.value,
                        "history": IntentClassifier._normalize_history(history),
                        "current_query": query.strip(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            self.primary_attempts += 1
            result = self._parse_response(self.llm.chat(messages))
        except Exception as exc:
            if self.fallback_llm is None:
                raise
            self.fallback_attempts += 1
            self.logger.warning(
                "[QUERY_PREPARATION] action=model_fallback error=%s query=%s",
                exc.__class__.__name__,
                query.strip(),
            )
            result = self._parse_response(self.fallback_llm.chat(messages))
        if not result.standalone_query:
            raise ValueError("standalone_query is required")
        result.filters = deepcopy(
            {
                key: value
                for key, value in result.filters.items()
                if key in self.FILTER_KEYS and value not in (None, "", [])
            }
        )
        self.logger.info(
            "[QUERY_PREPARATION] intent=%s sub_queries=%d query=%s",
            intent,
            len(result.sub_queries),
            query.strip(),
        )
        return result

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> QueryPreparationResult:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")
        payload = IntentClassifier._extract_json_object(content.strip())
        try:
            return QueryPreparationResult.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"query preparation response is invalid: {exc}") from exc

    @staticmethod
    def _system_prompt(intent: QueryIntent) -> str:
        intent_instruction = {
            QueryIntent.COMPARISON: (
                "Create one self-contained sub-query for each comparison target."
            ),
            QueryIntent.SUMMARIZATION: (
                "Plan retrieval queries that cover the requested summary topic."
            ),
            QueryIntent.DOCUMENT_SEARCH: (
                "Preserve explicit document identity and filter constraints."
            ),
            QueryIntent.KNOWLEDGE_QA: (
                "Use sub_queries only for genuinely multi-part questions."
            ),
        }.get(intent, "Do not create unnecessary sub-queries.")
        return (
            "Prepare a retrieval query for an enterprise knowledge Agent. "
            "The intent has already been classified; never change it. Resolve "
            "references using history and rewrite the request into one faithful, "
            "self-contained standalone_query. Preserve technical identifiers and "
            "never add facts. Return JSON only with exactly standalone_query, "
            "sub_queries, filters, reason. Return at most four unique sub_queries. "
            "Supported filter keys are doc_id, doc_ids, space, doc_type; never "
            "infer unstated filters. "
            + intent_instruction
        )
