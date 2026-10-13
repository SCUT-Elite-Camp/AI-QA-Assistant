"""Deterministic handling for explicit confirmed-Fact recall requests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import time
import unicodedata

from agent.config.settings import settings
from agent.memory.fact_visibility import visible_session_facts
from agent.memory.persistent_models import PersistentFact
from agent.schemas.chat import MemoryRecall


class MemoryResponsePolicy:
    """Return visible confirmed SESSION Facts without a database or model call."""

    _EXACT_RECALL_COMMANDS = frozenset(
        {
            "我记住了什么",
            "我之前确认的记忆是什么",
            "what have you remembered",
            "what are my confirmed memories",
        }
    )

    def __init__(self, *, now_ms: Callable[[], int] | None = None) -> None:
        self._now_ms = now_ms or (lambda: int(time() * 1000))

    def resolve(
        self, query: str, facts: Sequence[PersistentFact], *, visibility_cutoff_ms: int | None = None
    ) -> MemoryRecall:
        """Handle only exact opt-in recall commands; ordinary questions remain model-bound."""
        normalized_query = unicodedata.normalize("NFC", query).strip().casefold()
        # A final Chinese or ASCII question mark is presentation punctuation,
        # not part of the deterministic command. Remove at most one so
        # ordinary free-form questions remain model-bound.
        if normalized_query.endswith(("?", "？")):
            normalized_query = normalized_query[:-1].rstrip()
        if (
            not settings.SESSION_FACT_ENABLED
            or normalized_query not in self._EXACT_RECALL_COMMANDS
        ):
            return MemoryRecall(handled=False)

        visible_facts = visible_session_facts(
            facts, now_ms=self._now_ms() if visibility_cutoff_ms is None else visibility_cutoff_ms
        )
        if not visible_facts:
            return MemoryRecall(handled=True, answer="当前没有可见且未过期的已确认记忆。")

        # The BFF passes visible Facts in its canonical createdAt/id order.
        lines = [f"- {fact.category}: {fact.value.strip()}" for fact in visible_facts]
        return MemoryRecall(handled=True, answer="已确认的记忆：\n" + "\n".join(lines))
