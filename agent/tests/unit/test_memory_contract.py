import pytest
from pydantic import ValidationError

from agent.schemas.chat import (
    ChatResponse,
    InternalChatRequest,
    InternalChatResponse,
    MemoryDecision,
)


def memory_context_payload() -> dict:
    return {
        "actor": {"user_id": "user-a", "authenticated": True},
        "chat_id": "chat-a",
        "revision": 2,
        "current_message_id": "message-3",
        "current_sequence": 3,
        "snapshot": {
            "id": "snapshot-1",
            "version": 1,
            "revision": 2,
            "covered_to_sequence": 1,
            "summary": "A persisted summary.",
        },

        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 2,
                "role": "assistant",
                "content": "Previous response.",
            }
        ],
    }


def test_internal_chat_request_round_trips_the_memory_context() -> None:
    request = InternalChatRequest(
        query="Continue the previous topic.",
        memory_context=memory_context_payload(),
    )

    dumped = request.model_dump(mode="json")
    assert dumped["memory_context"]["actor"] == {"user_id": "user-a", "authenticated": True}
    assert InternalChatRequest.model_validate(dumped) == request


def test_internal_memory_contract_rejects_untrusted_or_inconsistent_input() -> None:
    unknown = memory_context_payload()
    unknown["untrusted_user_id"] = "user-b"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        InternalChatRequest(query="question", memory_context=unknown)

    invalid_actor = memory_context_payload()
    invalid_actor["actor"]["authenticated"] = False
    with pytest.raises(ValidationError):
        InternalChatRequest(query="question", memory_context=invalid_actor)

    invalid_tail = memory_context_payload()
    invalid_tail["tail"][0]["sequence"] = 3
    with pytest.raises(ValidationError, match="tail message sequence"):
        InternalChatRequest(query="question", memory_context=invalid_tail)

    covered_tail = memory_context_payload()
    covered_tail["tail"][0]["sequence"] = covered_tail["snapshot"]["covered_to_sequence"]
    with pytest.raises(ValidationError, match="tail message sequence"):
        InternalChatRequest(query="question", memory_context=covered_tail)


def test_internal_response_keeps_memory_decision_outside_public_chat_response() -> None:
    public_response = ChatResponse(
        trace_id="trace-1",
        status="success",
        answer="Answer.",
        message="",
        citations=[],
    )
    internal_response = InternalChatResponse(
        response=public_response,
        memory_decision=MemoryDecision(),
    )

    assert set(internal_response.response.model_dump(exclude_none=True)) == {
        "trace_id",
        "status",
        "answer",
        "message",
        "citations",
        "answer_claims",
    }


def test_removed_fact_fields_are_rejected_by_internal_contract() -> None:
    context = memory_context_payload()
    context["facts"] = []
    with pytest.raises(ValidationError, match="facts"):
        InternalChatRequest(query="Continue the discussion.", memory_context=context)
    for field in ("fact_proposals", "recall"):
        with pytest.raises(ValidationError, match=field):
            MemoryDecision.model_validate({field: [] if field == "fact_proposals" else {"handled": True}})
