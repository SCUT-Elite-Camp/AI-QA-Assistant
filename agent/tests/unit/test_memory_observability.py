from __future__ import annotations

import pytest

from agent.memory.memory_observability import MemoryObservability


def test_observability_emits_only_documented_content_free_payloads() -> None:
    events: list[tuple[str, dict[str, str | int]]] = []
    observability = MemoryObservability(
        emit=lambda event, payload: events.append((event, payload))
    )

    observability.resolve(
        source="trusted_context",
        outcome="success",
        duration_ms=7,
    )
    observability.compaction(
        outcome="planned",
        tail_count=8,
        snapshot_version=2,
    )
    observability.fact(action="recalled", outcome="success")

    assert events == [
        (
            "memory_resolve",
            {"source": "trusted_context", "outcome": "success", "duration_ms": 7},
        ),
        (
            "memory_compaction",
            {"outcome": "planned", "tail_count": 8, "snapshot_version": 2},
        ),
        ("memory_fact", {"action": "recalled", "outcome": "success"}),
    ]
    forbidden = {
        "fact",
        "value",
        "summary",
        "tail",
        "query",
        "prompt",
        "message_id",
        "chat_id",
        "token",
    }
    assert all(not (forbidden & set(payload)) for _, payload in events)


@pytest.mark.parametrize(
    "call",
    [
        lambda observer: observer.resolve(
            source="untrusted",  # type: ignore[arg-type]
            outcome="success",
            duration_ms=1,
        ),
        lambda observer: observer.resolve(
            source="legacy",
            outcome="unexpected",  # type: ignore[arg-type]
            duration_ms=1,
        ),
        lambda observer: observer.resolve(
            source="legacy",
            outcome="success",
            duration_ms=-1,
        ),
        lambda observer: observer.compaction(
            outcome="skipped",
            tail_count=0,
            snapshot_version=0,
        ),
        lambda observer: observer.fact(
            action="stored",  # type: ignore[arg-type]
            outcome="success",
        ),
    ],
)
def test_observability_rejects_unknown_labels_and_invalid_numbers(call) -> None:
    with pytest.raises(ValueError):
        call(MemoryObservability(emit=lambda _event, _payload: None))


def test_observability_sink_failure_does_not_escape() -> None:
    def fail_sink(_event: str, _payload: dict[str, str | int]) -> None:
        raise RuntimeError("user content must not be logged")

    MemoryObservability(emit=fail_sink).fact(action="suppressed", outcome="failed")
