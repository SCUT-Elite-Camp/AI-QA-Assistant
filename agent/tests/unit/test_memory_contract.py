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
        "facts": [
            {
                "id": "fact-1",
                "category": "PREFERENCE",
                "value": "Use concise Chinese responses.",
                "expires_at": None,
            }
        ],
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
    assert dumped["memory_context"]["facts"][0]["expires_at"] is None
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

    invalid_category = memory_context_payload()
    invalid_category["facts"][0]["category"] = "USER_SCOPE"
    with pytest.raises(ValidationError):
        InternalChatRequest(query="question", memory_context=invalid_category)

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
    }
    assert internal_response.memory_decision.fact_proposals == []
