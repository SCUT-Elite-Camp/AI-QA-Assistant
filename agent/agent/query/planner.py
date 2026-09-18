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
from agent.query.source_intent import heuristic_source_intent
from agent.schemas.query_plan import QueryIntent


class QueryPlanner:
    """Generate bounded retrieval sub-queries and supported semantic filters."""

    FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})
    SUPPORTED_DOC_TYPES = frozenset(
        {
            "csv",
            "doc",
            "docx",
            "epub",
            "htm",
            "html",
            "json",
            "md",
            "markdown",
            "odp",
            "ods",
            "odt",
            "pdf",
            "ppt",
            "pptx",
            "rst",
            "rtf",
            "txt",
            "xls",
            "xlsx",
            "xml",
        }
    )
    _DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
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
            return QueryEnrichment(
                source_intent=heuristic_source_intent(
                    query,
                    enterprise_default=intent in self.RETRIEVAL_INTENTS,
                ),
                reason="query_planning_skipped",
            )

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
            return QueryEnrichment(
                source_intent=heuristic_source_intent(query),
                reason="query_planning_failed",
            )

        return QueryEnrichment(
            sub_queries=result.sub_queries,
            filters=self._supported_filters(result.filters),
            source_intent=(
                result.source_intent
                if result.source_intent.sources
                else heuristic_source_intent(query)
            ),
            reason=result.reason,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Plan retrieval for an enterprise knowledge Agent. "
            "Return JSON only with keys sub_queries, filters, source_intent, and reason. "
            "source_intent has sources (any of personal_library, enterprise_kb, "
            "conversation_attachment, web), mode (explicit or inferred), and optional "
            "confidence. It may contain multiple sources for comparison. Source intent "
            "selects retrieval sources only and must never contain user IDs, knowledge "
            "base IDs, tokens, or authorization data. "
            "For comparison, create one self-contained sub-query per comparison "
            "target. For other intents, use sub_queries only when decomposition "
            "materially improves retrieval. Return at most four sub-queries. "
            "Extract filters only when explicitly stated by the user. Supported "
            "filter keys are doc_id, doc_ids, space, and doc_type. Do not infer "
            "unstated facts or add any other filter key. doc_type means a real "
            "file extension such as pdf, doc, docx, md, or txt; a content category "
            "such as meeting minutes, policy, report, or contract must remain in "
            "the retrieval query and must not be emitted as doc_type. A document title or "
            "filename is not a doc_id; emit doc_id only for an explicit opaque "
            "identifier. Example shape: "
            '{"sub_queries":[],"filters":{},"source_intent":{"sources":'
            '["enterprise_kb"],"mode":"inferred","confidence":0.8},'
            '"reason":"not needed"}'
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
        supported: dict[str, Any] = {}
        space = filters.get("space")
        if isinstance(space, str) and space.strip():
            supported["space"] = space.strip()

        doc_type = filters.get("doc_type")
        if isinstance(doc_type, str):
            normalized_doc_type = (
                doc_type.strip().lower().rsplit("/", 1)[-1].removeprefix(".")
            )
            if normalized_doc_type in cls.SUPPORTED_DOC_TYPES:
                supported["doc_type"] = normalized_doc_type

        doc_id = filters.get("doc_id")
        if isinstance(doc_id, str) and cls._DOC_ID_PATTERN.fullmatch(doc_id):
            supported["doc_id"] = doc_id

        doc_ids = filters.get("doc_ids")
        if isinstance(doc_ids, list):
            valid_ids = [
                value
                for value in doc_ids
                if isinstance(value, str) and cls._DOC_ID_PATTERN.fullmatch(value)
            ]
            if valid_ids:
                supported["doc_ids"] = valid_ids

        return deepcopy(supported)
