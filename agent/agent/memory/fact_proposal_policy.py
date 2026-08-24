"""Pure, opt-in parsing for internal SESSION Fact proposal candidates."""

from __future__ import annotations

import re
import unicodedata

from agent.memory.sensitive_value import isSensitiveMemoryValue
from agent.memory.memory_observability import MemoryObservability
from agent.schemas.chat import FactProposal, MemoryFactCategory


_WHITESPACE = re.compile(r"\s+")
_COMMANDS: tuple[tuple[MemoryFactCategory, re.Pattern[str]], ...] = (
    ("GOAL", re.compile(r"^(?:请)?记住目标[：:](?P<value>[\s\S]*)$", re.IGNORECASE)),
    ("PREFERENCE", re.compile(r"^(?:请)?记住偏好[：:](?P<value>[\s\S]*)$", re.IGNORECASE)),
    (
        "PLAN_CONSTRAINT",
        re.compile(r"^(?:请)?记住计划约束[：:](?P<value>[\s\S]*)$", re.IGNORECASE),
    ),
    ("GOAL", re.compile(r"^remember goal[：:](?P<value>[\s\S]*)$", re.IGNORECASE)),
    (
        "PREFERENCE",
        re.compile(r"^remember preference[：:](?P<value>[\s\S]*)$", re.IGNORECASE),
    ),
    (
        "PLAN_CONSTRAINT",
        re.compile(r"^remember plan constraint[：:](?P<value>[\s\S]*)$", re.IGNORECASE),
    ),
)
_MAX_VALUE_CODE_POINTS = 500


class FactProposalPolicy:
    """Generate at most one non-sensitive internal Fact candidate per request."""

    def __init__(self, *, observability: MemoryObservability | None = None) -> None:
        self._observability = observability or MemoryObservability()

    def propose(
        self,
        query: str,
        *,
        actor_authenticated: bool,
        current_message_id: str,
        persistent_memory_enabled: bool,
        session_fact_enabled: bool,
    ) -> list[FactProposal]:
        if (
            not persistent_memory_enabled
            or not session_fact_enabled
            or not actor_authenticated
            or not current_message_id
        ):
            self._observability.fact(action="suppressed", outcome="disabled")
            return []

        parsed = self._parse(query)
        if parsed is None:
            self._observability.fact(action="suppressed", outcome="empty")
            return []

        category, value = parsed
        if isSensitiveMemoryValue(value):
            self._observability.fact(action="suppressed", outcome="sensitive")
            return []

        proposals = [
            FactProposal(
                category=category,
                value=value,
                source_message_id=current_message_id,
                expires_at=None,
            )
        ]
        self._observability.fact(action="proposed", outcome="success")
        return proposals

    @staticmethod
    def _parse(query: str) -> tuple[MemoryFactCategory, str] | None:
        normalized_query = unicodedata.normalize("NFC", query).strip()
        for category, command in _COMMANDS:
            match = command.fullmatch(normalized_query)
            if match is None:
                continue

            value = _WHITESPACE.sub(" ", match.group("value")).strip()
            if not value or len(value) > _MAX_VALUE_CODE_POINTS:
                return None
            return category, value
        return None
