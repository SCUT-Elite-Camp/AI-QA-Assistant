from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.config.settings import Settings, settings
from agent.memory.compaction_planner import CompactionPlanner
from agent.memory.context_resolver import ContextResolver
from agent.memory.memory_observability import MemoryObservability
from agent.schemas.chat import (
    CompactionPlan,
    CompactionPlanRequest,
    InternalActor,
    MemoryContextInput,
    MemoryMessage,
    MemorySnapshotInput,
    NoCompactionPlan,
)


pytestmark = pytest.mark.no_storage


def _message(
    sequence: int,
    *,
    content: str | None = None,
    role: str | None = None,
) -> MemoryMessage:
    return MemoryMessage(
        id=f"m{sequence}",
        sequence=sequence,
        revision=1,
        role=role or ("user" if sequence % 2 else "assistant"),  # type: ignore[arg-type]
        content=content or f"message-{sequence}",
    )


def _request(
    messages: list[MemoryMessage],
    *,
    active_snapshot: MemorySnapshotInput | None = None,
    include_legacy_thresholds: bool = True,
    tail_size: int = 8,
    min_coverable_messages: int = 12,
    soft_token_budget: int = 1000,
) -> CompactionPlanRequest:
    payload: dict[str, object] = {
        "actor": InternalActor(user_id="user-1", authenticated=True),
        "chat_id": "chat-1",
        "revision": 1,
        "active_snapshot": active_snapshot,
        "messages": messages,
    }
    if include_legacy_thresholds:
        payload.update(
            {
                "tail_size": tail_size,
                "min_coverable_messages": min_coverable_messages,
                "soft_token_budget": soft_token_budget,
            }
        )
    return CompactionPlanRequest.model_validate(payload)


def test_eleven_coverable_messages_do_not_create_a_snapshot() -> None:
    request = _request(
        [_message(sequence) for sequence in range(1, 21)],
        active_snapshot=MemorySnapshotInput(
            id="snapshot-1",
            version=1,
            revision=1,
            covered_to_sequence=1,
            summary="Earlier summary.",
        ),
    )

    plan = CompactionPlanner().plan(request)

    assert isinstance(plan, NoCompactionPlan)


def test_twelve_coverable_messages_create_the_initial_snapshot() -> None:
    plan = CompactionPlanner().plan(_request([_message(sequence) for sequence in range(1, 21)]))

    assert isinstance(plan, CompactionPlan)
    assert plan.expected_active_snapshot is None
    assert plan.new_snapshot.covered_from_sequence == 1
    assert plan.new_snapshot.covered_to_sequence == 12
    assert plan.new_snapshot.covered_from_message_id == "m1"
    assert plan.new_snapshot.covered_to_message_id == "m12"
    assert "message-12" in plan.new_snapshot.summary
    assert "message-13" not in plan.new_snapshot.summary


def test_token_budget_can_trigger_compaction_before_message_threshold() -> None:
    messages = [
        _message(sequence, content="x" * 450)
        for sequence in range(1, 19)
    ]

    plan = CompactionPlanner().plan(_request(messages))

    assert isinstance(plan, CompactionPlan)
    assert plan.new_snapshot.covered_to_sequence == 10


def test_trailing_unpaired_user_message_is_neither_covered_nor_summarized() -> None:
    messages = [_message(sequence) for sequence in range(1, 22)]
    messages[-1] = _message(21, content="current query must remain raw", role="user")

    plan = CompactionPlanner().plan(_request(messages))

    assert isinstance(plan, CompactionPlan)
    assert plan.new_snapshot.covered_to_sequence == 12
    assert "current query must remain raw" not in plan.new_snapshot.summary


def test_active_snapshot_is_used_as_optimistic_version_precondition() -> None:
    active_snapshot = MemorySnapshotInput(
        id="snapshot-2",
        version=2,
        revision=1,
        covered_to_sequence=4,
        summary="Previous durable summary.",
    )

    plan = CompactionPlanner().plan(
        _request([_message(sequence) for sequence in range(1, 25)], active_snapshot=active_snapshot)
    )

    assert isinstance(plan, CompactionPlan)
    assert plan.expected_active_snapshot is not None
    assert plan.expected_active_snapshot.id == "snapshot-2"
    assert plan.expected_active_snapshot.version == 2
    assert plan.expected_active_snapshot.revision == 1
    assert plan.new_snapshot.covered_from_sequence == 5
    assert plan.new_snapshot.covered_to_sequence == 16
    assert "Previous durable summary." in plan.new_snapshot.summary


def test_sensitive_messages_and_sensitive_previous_summary_are_never_retained() -> None:
    messages = [_message(sequence) for sequence in range(1, 23)]
    messages[1] = _message(2, content="API KEY=must-not-persist", role="assistant")
    messages[3] = _message(4, content="11010519491231002X", role="assistant")
    active_snapshot = MemorySnapshotInput(
        id="snapshot-2",
        version=2,
        revision=1,
        covered_to_sequence=1,
        summary="previous TOKEN must-not-persist",
    )

    plan = CompactionPlanner().plan(_request(messages, active_snapshot=active_snapshot))

    assert isinstance(plan, CompactionPlan)
    assert "must-not-persist" not in plan.new_snapshot.summary
    assert "11010519491231002X" not in plan.new_snapshot.summary


def test_summary_is_bounded_and_prioritizes_new_covered_messages() -> None:
    plan = CompactionPlanner(summary_max_chars=100).plan(
        _request(
            [_message(sequence, content="normal text " * 30) for sequence in range(1, 23)],
            active_snapshot=MemorySnapshotInput(
                id="snapshot-1",
                version=1,
                revision=1,
                covered_to_sequence=1,
                summary="old summary " * 30,
            ),
        )
    )

    assert isinstance(plan, CompactionPlan)
    assert len(plan.new_snapshot.summary) <= 100
    assert plan.new_snapshot.summary.startswith("[New covered messages]")


def test_plan_boundary_rebuilds_snapshot_plus_tail_without_current_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    messages = [_message(sequence) for sequence in range(1, 22)]
    messages[-1] = _message(21, content="current query", role="user")
    plan = CompactionPlanner().plan(_request(messages))

    assert isinstance(plan, CompactionPlan)
    artifact = ContextResolver(tail_messages=8).resolve(
        MemoryContextInput(
            actor=InternalActor(user_id="user-1", authenticated=True),
            chat_id="chat-1",
            revision=1,
            current_message_id="m21",
            current_sequence=21,
            snapshot=MemorySnapshotInput(
                id="snapshot-next",
                version=1,
                revision=1,
                covered_to_sequence=plan.new_snapshot.covered_to_sequence,
                summary=plan.new_snapshot.summary,
            ),
            facts=[],
            tail=messages[12:20],
        )
    )

    assert artifact is not None
    assert [message.id for message in artifact.model_history[1:]] == [
        f"m{sequence}" for sequence in range(13, 21)
    ]
    assert "current query" not in "\n".join(
        message.content for message in artifact.model_history
    )


def test_snapshot_summary_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(MEMORY_SNAPSHOT_SUMMARY_MAX_CHARS=0)
    with pytest.raises(ValueError, match="summary_max_chars"):
        CompactionPlanner(summary_max_chars=0)


def test_legacy_and_omitted_bff_thresholds_produce_the_same_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEMORY_TAIL_MESSAGES", 2)
    monkeypatch.setattr(settings, "MEMORY_COMPACTION_MIN_MESSAGES", 1)
    monkeypatch.setattr(settings, "MEMORY_COMPACTION_SOFT_TOKENS", 1_000)
    messages = [_message(sequence) for sequence in range(1, 5)]

    legacy_plan = CompactionPlanner().plan(
        _request(
            messages,
            tail_size=8,
            min_coverable_messages=12,
            soft_token_budget=1_000,
        )
    )
    omitted_plan = CompactionPlanner().plan(
        _request(messages, include_legacy_thresholds=False)
    )

    assert isinstance(legacy_plan, CompactionPlan)
    assert legacy_plan == omitted_plan
    assert legacy_plan.new_snapshot.covered_from_sequence == 1
    assert legacy_plan.new_snapshot.covered_to_sequence == 2


def test_only_agent_settings_can_change_compaction_threshold_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [_message(sequence) for sequence in range(1, 5)]
    monkeypatch.setattr(settings, "MEMORY_TAIL_MESSAGES", 2)
    monkeypatch.setattr(settings, "MEMORY_COMPACTION_MIN_MESSAGES", 3)
    monkeypatch.setattr(settings, "MEMORY_COMPACTION_SOFT_TOKENS", 10_000)

    legacy_request = _request(
        messages,
        tail_size=1,
        min_coverable_messages=1,
        soft_token_budget=1,
    )
    omitted_request = _request(messages, include_legacy_thresholds=False)
    assert isinstance(CompactionPlanner().plan(legacy_request), NoCompactionPlan)
    assert CompactionPlanner().plan(legacy_request) == CompactionPlanner().plan(omitted_request)

    monkeypatch.setattr(settings, "MEMORY_COMPACTION_MIN_MESSAGES", 1)
    assert isinstance(CompactionPlanner().plan(legacy_request), CompactionPlan)
    assert CompactionPlanner().plan(legacy_request) == CompactionPlanner().plan(omitted_request)


def test_planner_failure_returns_no_plan_and_only_safe_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, str | int]]] = []
    planner = CompactionPlanner(
        tail_messages=2,
        min_coverable_messages=1,
        soft_token_budget=1_000,
        observability=MemoryObservability(
            emit=lambda event, payload: events.append((event, payload))
        ),
    )

    def fail_summary(*args: object, **kwargs: object) -> str:
        raise RuntimeError("do not expose this message content")

    monkeypatch.setattr(planner, "_build_summary", fail_summary)

    assert isinstance(
        planner.plan(_request([_message(sequence) for sequence in range(1, 5)])),
        NoCompactionPlan,
    )
    assert events == [
        ("memory_compaction", {"outcome": "failed", "tail_count": 0})
    ]


@pytest.mark.parametrize(
    "field_name",
    ["MEMORY_COMPACTION_MIN_MESSAGES", "MEMORY_COMPACTION_SOFT_TOKENS"],
)
def test_compaction_settings_limits_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field_name: 0})
