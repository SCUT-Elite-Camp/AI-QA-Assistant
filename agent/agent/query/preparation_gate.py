import re
from typing import Any

from agent.query.schemas import IntentResult
from agent.schemas.query_plan import QueryIntent


class QueryPreparationGate:
    """Bypass LLM preparation only for clearly standalone, single-target QA."""

    _REFERENCE_PATTERN = re.compile(
        r"\b(?:it|this|that|they|them|these|those|former|latter|previous|above)\b",
        flags=re.IGNORECASE,
    )
    _COMPLEX_PATTERN = re.compile(
        r"\b(?:compare|comparison|contrast|versus|vs\.?|difference|differences|"
        r"separately|respectively|both|summarize|summary|then)\b"
        r"|\band\s+(?:why|how|what|which|where|when)\b",
        flags=re.IGNORECASE,
    )

    @classmethod
    def can_bypass(
        cls,
        query: str,
        history: list[dict[str, Any]],
        intent: IntentResult,
    ) -> bool:
        """Return true only when preparation cannot materially improve the query."""
        normalized = query.strip()
        if intent.intent != QueryIntent.KNOWLEDGE_QA:
            return False
        if intent.is_follow_up or intent.is_clarification_reply:
            return False
        if cls._has_conversation_history(history):
            return False
        if not normalized or len(normalized) > 160 or normalized.count("?") > 1:
            return False
        if "\ufffd" in normalized or not re.search(r"[A-Za-z]{3}", normalized):
            return False
        if cls._REFERENCE_PATTERN.search(normalized):
            return False
        if cls._COMPLEX_PATTERN.search(normalized):
            return False
        return True

    @staticmethod
    def _has_conversation_history(history: list[dict[str, Any]]) -> bool:
        return any(
            isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
            and item["content"].strip()
            for item in history
        )
