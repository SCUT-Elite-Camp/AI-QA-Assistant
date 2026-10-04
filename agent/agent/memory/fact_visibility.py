"""Shared deterministic visibility rules for request-local persistent Facts."""

from collections.abc import Iterable
import time

from agent.memory.persistent_models import PersistentFact


def current_time_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def visible_session_facts(
    facts: Iterable[PersistentFact],
    *,
    now_ms: int,
) -> list[PersistentFact]:
    """Select confirmed, non-empty SESSION Facts visible at one fixed cutoff."""
    return [
        fact
        for fact in facts
        if fact.status == "CONFIRMED"
        and fact.scope == "SESSION"
        and fact.value.strip()
        and (fact.expires_at is None or fact.expires_at > now_ms)
    ]
