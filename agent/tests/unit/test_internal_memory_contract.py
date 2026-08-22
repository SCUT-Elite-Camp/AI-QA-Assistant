"""Unit 04: strict, Agent-side DTO contract for private Memory endpoints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.config.settings import Settings
from agent.schemas.chat import (
    ChatRequest,
    CompactionPlan,
    CompactionPlanRequest,
    InternalChatRequest,
    MemoryContextInput,
    NoCompactionPlan,
    ResetShortWindowRequest,
    ResetShortWindowResponse,
)


def _memory_context() -> dict[str, object]:
    return {
        "actor": {"user_id": "user-1", "authenticated": True},
        "chat_id": "chat-1",
        "revision": 1,
        "current_message_id": "message-3",
        "current_sequence": 3,
        "snapshot": {
            "id": "snapshot-1",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 1,
            "summary": "Earlier discussion.",
        },
        "facts": [
            {
                "id": "fact-1",
                "category": "GOAL",
                "value": "Prepare the project demo.",
                "expires_at": None,
            }
        ],
        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 1,
                "role": "assistant",
                "content": "What would you like to know?",
            }
        ],
    }


def test_internal_chat_request_accepts_strict_memory_context() -> None:
    request = InternalChatRequest.model_validate(
        {
            "query": "What was my goal?",
            "session_id": "chat-1",
            "memory_context": _memory_context(),
        }
    )

    assert request.memory_context.actor.authenticated is True
    assert request.memory_context.facts[0].category == "GOAL"
    assert request.memory_context.snapshot is not None


@pytest.mark.parametrize(
    ("mutate", "expected_field"),
    [
        (lambda context: context.update({"unexpected": "value"}), "unexpected"),
        (
            lambda context: context["actor"].update({"authenticated": False}),
            "authenticated",
        ),
        (
            lambda context: context["facts"][0].update({"category": "USER_SCOPE"}),
            "category",
        ),
        (
            lambda context: context["facts"][0].update({"expires_at": "tomorrow"}),
            "expires_at",
        ),
    ],
)
def test_internal_memory_context_rejects_invalid_input(mutate, expected_field: str) -> None:
    context = _memory_context()
    mutate(context)

    with pytest.raises(ValidationError) as error:
        MemoryContextInput.model_validate(context)

    assert expected_field in str(error.value)


def test_public_chat_request_rejects_internal_memory_context() -> None:
    with pytest.raises(ValidationError, match="memory_context"):
        ChatRequest.model_validate(
            {"query": "A public request", "memory_context": _memory_context()}
        )


def test_internal_compaction_and_reset_dtos_are_discriminated() -> None:
    no_compaction = NoCompactionPlan.model_validate({"should_compact": False})
    assert no_compaction.should_compact is False

    compaction = CompactionPlan.model_validate(
        {
            "should_compact": True,
            "expected_active_snapshot": {
                "id": "snapshot-1",
                "version": 1,
                "revision": 1,
            },
            "new_snapshot": {
                "covered_from_sequence": 1,
                "covered_to_sequence": 12,
                "covered_from_message_id": "message-1",
                "covered_to_message_id": "message-12",
                "summary": "Compressed discussion.",
            },
        }
    )
    assert compaction.new_snapshot.covered_to_sequence == 12

    compaction_request = CompactionPlanRequest.model_validate(
        {
            "actor": {"user_id": "user-1", "authenticated": True},
            "chat_id": "chat-1",
            "revision": 1,
            "active_snapshot": None,
            "messages": [],
            "tail_size": 8,
            "min_coverable_messages": 12,
            "soft_token_budget": 1000,
        }
    )
    assert compaction_request.active_snapshot is None
    assert ResetShortWindowRequest.model_validate({"chat_id": "chat-1"}).chat_id == "chat-1"
    assert ResetShortWindowResponse.model_validate({"status": "ok"}).status == "ok"


def test_persistent_memory_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERSISTENT_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_INTERNAL_TOKEN", raising=False)
    assert Settings().PERSISTENT_MEMORY_ENABLED is False
    assert Settings().AGENT_INTERNAL_TOKEN == ""

    monkeypatch.setenv("PERSISTENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-token")
    assert Settings().PERSISTENT_MEMORY_ENABLED is True
    assert Settings().AGENT_INTERNAL_TOKEN == "test-token"
