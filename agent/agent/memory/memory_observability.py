"""Safe, bounded observability events for persistent Chat Memory.

The helper deliberately has no access to request bodies or storage.  Its
public methods only accept the finite labels and numbers documented by Unit
11, so callers cannot accidentally emit a Fact, Snapshot, Tail, query, ID, or
token through this seam.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal


_LOGGER = logging.getLogger("agent-layer.memory")

MemoryResolveSource = Literal["disabled", "trusted_context", "legacy"]
MemoryResolveOutcome = Literal["success", "fallback", "rejected"]
MemoryCompactionOutcome = Literal["skipped", "planned", "conflict", "failed"]
MemoryFactAction = Literal["proposed", "suppressed", "recalled"]
MemoryFactOutcome = Literal["success", "disabled", "sensitive", "empty", "failed"]
MemoryEventPayload = dict[str, str | int]
MemoryEventSink = Callable[[str, MemoryEventPayload], None]


class MemoryObservability:
    """Emit only allow-listed, content-free Memory event payloads."""

    def __init__(self, *, emit: MemoryEventSink | None = None) -> None:
        self._emit = emit or self._log_event

    def resolve(
        self,
        *,
        source: MemoryResolveSource,
        outcome: MemoryResolveOutcome,
        duration_ms: int,
    ) -> None:
        self._require(source, {"disabled", "trusted_context", "legacy"}, "source")
        self._require(outcome, {"success", "fallback", "rejected"}, "outcome")
        self._require_non_negative(duration_ms, "duration_ms")
        self._publish(
            "memory_resolve",
            {"source": source, "outcome": outcome, "duration_ms": duration_ms},
        )

    def compaction(
        self,
        *,
        outcome: MemoryCompactionOutcome,
        tail_count: int,
        snapshot_version: int | None = None,
    ) -> None:
        self._require(outcome, {"skipped", "planned", "conflict", "failed"}, "outcome")
        self._require_non_negative(tail_count, "tail_count")
        payload: MemoryEventPayload = {"outcome": outcome, "tail_count": tail_count}
        if snapshot_version is not None:
            if snapshot_version < 1:
                raise ValueError("snapshot_version must be positive")
            payload["snapshot_version"] = snapshot_version
        self._publish("memory_compaction", payload)

    def fact(
        self,
        *,
        action: MemoryFactAction,
        outcome: MemoryFactOutcome,
    ) -> None:
        self._require(action, {"proposed", "suppressed", "recalled"}, "action")
        self._require(
            outcome,
            {"success", "disabled", "sensitive", "empty", "failed"},
            "outcome",
        )
        self._publish("memory_fact", {"action": action, "outcome": outcome})

    def _publish(self, event_name: str, payload: MemoryEventPayload) -> None:
        """Keep optional observability from changing Chat or planning results."""
        try:
            self._emit(event_name, payload)
        except Exception as exc:
            # Both values are allow-listed metadata. Never attach ``exc_info``:
            # an exception can carry user text in its arguments.
            _LOGGER.warning(
                "memory_observability_emit_failed event=%s exception=%s",
                event_name,
                type(exc).__name__,
            )

    @staticmethod
    def _require(value: str, allowed: set[str], field_name: str) -> None:
        if value not in allowed:
            raise ValueError(f"unsupported {field_name}")

    @staticmethod
    def _require_non_negative(value: int, field_name: str) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")

    @staticmethod
    def _log_event(event_name: str, payload: MemoryEventPayload) -> None:
        # The payload was constructed exclusively from allow-listed values.
        _LOGGER.info("%s %s", event_name, payload)
