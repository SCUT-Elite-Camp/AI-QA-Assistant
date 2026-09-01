import json
import logging
from typing import Any

from pydantic import ValidationError

from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.intent_classifier import IntentClassifier
from agent.query.schemas import UnifiedQueryResult


class UnifiedQueryAnalyzer:
    """Produce intent, clarification, rewrite, and retrieval plan in one call."""

    FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})

    def __init__(
        self,
        llm: BaseLLM | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.logger = logger or logging.getLogger("agent-layer.query")

    def analyze(
        self,
        query: str,
        history: list[dict[str, Any]],
    ) -> UnifiedQueryResult:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "history": IntentClassifier._normalize_history(history),
                        "current_query": query.strip(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        response = self.llm.chat(messages)
        result = self._parse_response(response)
        result.filters = {
            key: value
            for key, value in result.filters.items()
            if key in self.FILTER_KEYS and value not in (None, "", [])
        }
        if result.needs_clarification:
            if not result.clarification_question:
                raise ValueError("clarification_question is required")
            result.standalone_query = query.strip()
            result.sub_queries = []
            result.filters = {}
        elif not result.standalone_query:
            raise ValueError("standalone_query is required")

        self.logger.info(
            "[UNIFIED_QUERY_UNDERSTANDING] intent=%s confidence=%.3f "
            "needs_clarification=%s sub_queries=%d query=%s",
            result.intent,
            result.confidence,
            result.needs_clarification,
            len(result.sub_queries),
            query.strip(),
        )
        return result

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> UnifiedQueryResult:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")
        payload = IntentClassifier._extract_json_object(content.strip())
        try:
            return UnifiedQueryResult.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"unified query response is invalid: {exc}") from exc

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Analyze one request for an enterprise knowledge Agent in a single pass. "
            "Return JSON only with exactly these keys: intent, confidence, is_follow_up, "
            "is_clarification_reply, needs_clarification, clarification_question, "
            "ambiguity_reason, standalone_query, sub_queries, filters. "
            "confidence must be a JSON number from 0.0 to 1.0, never a word. "
            "Intent must be exactly one of knowledge_qa, document_search, "
            "summarization, comparison, casual_chat, system_help, unsupported. "
            "knowledge_qa asks for facts or explanations from knowledge sources. "
            "document_search asks to find or list documents. summarization asks "
            "to summarize material, including retrievable project material; an "
            "explicit request to summarize must use summarization. comparison "
            "compares two or more objects. casual_chat needs no retrieval. "
            "system_help is only for current runtime usage or capability "
            "instructions, not questions about documented project components. "
            "unsupported requests an unavailable action. Clarify only when information that "
            "is required to execute the request is genuinely missing. Resolve "
            "references with history and make standalone_query self-contained. "
            "Create at most four sub_queries only when decomposition improves "
            "retrieval, especially one per comparison target. Supported filter "
            "keys are doc_id, doc_ids, space, doc_type; never infer filters. "
            "When clarification is required, ask one concise question and return "
            "empty sub_queries and filters."
        )
