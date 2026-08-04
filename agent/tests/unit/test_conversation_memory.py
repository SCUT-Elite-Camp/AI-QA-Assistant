import pytest

from agent.memory import InMemoryConversationMemory


def test_same_session_returns_messages_in_order_and_as_defensive_copies() -> None:
    memory = InMemoryConversationMemory(max_messages=4)
    memory.add_message("session-a", "user", "问题")
    memory.add_message("session-a", "assistant", "回答")

    messages = memory.get_messages("session-a")
    messages[0]["content"] = "被外部修改"

    assert memory.get_messages("session-a") == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
    ]


def test_sessions_are_isolated_and_can_be_cleared() -> None:
    memory = InMemoryConversationMemory()
    memory.add_message("session-a", "user", "A")
    memory.add_message("session-b", "user", "B")

    memory.clear("session-a")

    assert memory.get_messages("session-a") == []
    assert memory.get_messages("session-b") == [{"role": "user", "content": "B"}]


def test_memory_retains_only_latest_messages() -> None:
    memory = InMemoryConversationMemory(max_messages=3)
    for index in range(5):
        memory.add_message("session-a", "user", f"message-{index}")

    assert [item["content"] for item in memory.get_messages("session-a")] == [
        "message-2",
        "message-3",
        "message-4",
    ]


@pytest.mark.parametrize("session_id", ["", "   ", None])
def test_memory_rejects_missing_session_id(session_id) -> None:
    memory = InMemoryConversationMemory()

    with pytest.raises(ValueError, match="session_id"):
        memory.get_messages(session_id)
