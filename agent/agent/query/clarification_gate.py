import logging
import re
from typing import Any

from agent.query.clarifier import Clarifier
from agent.query.schemas import ClarificationDecision


class ClarificationGate:
    """Use high-precision rules before asking the LLM clarifier."""

    _REFERENCE_PATTERN = re.compile(
        r"(?:^|[\s，,。.!！？?])(它|它们|这个|那个|这些|那些|上一个|前者|后者)"
        r"|\b(?:it|this|that|they|them|former|latter)\b",
        flags=re.IGNORECASE,
    )
    _ANCHOR_PATTERN = re.compile(
        r"[A-Z][A-Za-z0-9_]{2,}|[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+"
    )

    def __init__(
        self,
        clarifier: Clarifier | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.clarifier = clarifier or Clarifier()
        self.logger = logger or logging.getLogger("agent-layer.query")

    def evaluate(
        self,
        query: str,
        history: list[dict[str, Any]],
    ) -> ClarificationDecision:
        normalized = query.strip()
        if self._can_rule_continue(normalized, history):
            self.logger.info(
                "[CLARIFICATION_GATE] action=continue source=rule query=%s",
                normalized,
            )
            return ClarificationDecision(
                needs_clarification=False,
                question="",
                reason="deterministic_clear_query",
            )
        self.logger.info(
            "[CLARIFICATION_GATE] action=delegate source=llm query=%s",
            normalized,
        )
        return self.clarifier.evaluate(normalized, history)

    @classmethod
    def _can_rule_continue(
        cls,
        query: str,
        history: list[dict[str, Any]],
    ) -> bool:
        if not query:
            return False
        has_history = any(
            isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
            and item["content"].strip()
            for item in history
        )
        unresolved_reference = bool(cls._REFERENCE_PATTERN.search(query)) and not has_history
        if unresolved_reference and not cls._ANCHOR_PATTERN.search(query):
            return False
        return len(query) >= 4
