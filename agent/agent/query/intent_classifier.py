import json
import logging
from typing import Any

from pydantic import ValidationError

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.schemas import IntentResult, QueryIntent


class IntentClassifier:
    """Classify a user query into the frozen CP2 intent taxonomy."""

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

    def classify(
        self,
        query: str,
        history: list[dict],
    ) -> IntentResult:
        """Return a validated classification with a safe knowledge-QA fallback."""
        normalized_query = query.strip()

        if not normalized_query:
            return self._fallback("empty_query")

        if not self.enabled:
            return self._fallback("query_understanding_disabled")

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": self._build_input(normalized_query, history),
            },
        ]

        try:
            response = self.llm.chat(messages)
            result = self._parse_response(response)
        except Exception as exc:
            self.logger.warning(
                "[INTENT_CLASSIFICATION] action=fallback error=%s query=%s",
                exc.__class__.__name__,
                normalized_query,
            )
            return self._fallback("intent_classification_failed")

        self.logger.info(
            "[INTENT_CLASSIFICATION] intent=%s confidence=%.3f "
            "is_follow_up=%s is_clarification_reply=%s query=%s",
            result.intent,
            result.confidence,
            result.is_follow_up,
            result.is_clarification_reply,
            normalized_query,
        )
        return result

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You classify user requests for an enterprise knowledge Agent. "
            "Choose exactly one intent from: "
            "knowledge_qa, document_search, summarization, comparison, "
            "casual_chat, system_help, unsupported. "
            "knowledge_qa asks for a factual answer from knowledge sources. "
            "document_search asks to find or list documents. "
            "summarization asks to summarize provided or retrievable material. "
            "comparison asks to compare two or more objects. "
            "casual_chat is ordinary conversation that does not need retrieval. "
            "system_help asks about this system's real capabilities or usage. "
            "unsupported requests an action outside current system capabilities. "
            "Use conversation history to decide whether this is a follow-up. "
            "Set is_clarification_reply only when the user is clearly answering "
            "a clarification question in history; runtime state will verify it. "
            "Return JSON only, without Markdown, using this shape: "
            '{"intent":"knowledge_qa","confidence":0.0,'
            '"is_follow_up":false,"is_clarification_reply":false,'
            '"reason":"..."}'
        )

    @staticmethod
    def _build_input(query: str, history: list[dict]) -> str:
        return json.dumps(
            {
                "history": IntentClassifier._normalize_history(history),
                "current_query": query,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_history(history: list[dict]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for message in history or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            normalized.append({"role": role, "content": content})
        return normalized

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> IntentResult:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")

        payload = IntentClassifier._extract_json_object(content.strip())
        try:
            return IntentResult.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("LLM intent response is invalid") from exc

    @staticmethod
    def _extract_json_object(content: str) -> dict[str, Any]:
        if content.startswith("```") and content.endswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1]).strip()

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM intent response is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("LLM intent response must be a JSON object")
        return payload

    @staticmethod
    def _fallback(reason: str) -> IntentResult:
        return IntentResult(
            intent=QueryIntent.KNOWLEDGE_QA,
            confidence=0.0,
            is_follow_up=False,
            is_clarification_reply=False,
            reason=reason,
        )
