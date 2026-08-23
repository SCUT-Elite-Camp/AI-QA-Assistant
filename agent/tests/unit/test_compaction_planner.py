from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.config.settings import Settings, settings
from agent.memory.compaction_planner import CompactionPlanner
from agent.memory.context_resolver import ContextResolver
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
    tail_size: int = 8,
    min_coverable_messages: int = 12,
    soft_token_budget: int = 1000,
) -> CompactionPlanRequest:
    return CompactionPlanRequest(
        actor=InternalActor(user_id="user-1", authenticated=True),
        chat_id="chat-1",
        revision=1,
        active_snapshot=active_snapshot,
        messages=messages,
        tail_size=tail_size,
        min_coverable_messages=min_coverable_messages,
        soft_token_budget=soft_token_budget,
    )


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
