from unittest.mock import Mock

from agent.config.settings import settings
from agent.memory.coordinator import MemoryCoordinator
from agent.memory.persistent_models import PersistentMemoryContext
from agent.schemas.chat import ChatRequest, InternalChatRequest


def _memory_context() -> dict:
    return {
        "actor": {"user_id": "user-a", "authenticated": True},
        "chat_id": "chat-a",
        "revision": 1,
        "current_message_id": "message-3",
        "current_sequence": 3,
        "snapshot": {
            "id": "snapshot-a",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 1,
            "summary": "Earlier topic summary.",
        },

        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 1,
                "role": "assistant",
                "content": "The prior answer.",
            }
        ],
    }


def test_prepare_builds_one_view_from_persistent_snapshot_and_tail(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    memory_context = _memory_context()
    original_from_input = PersistentMemoryContext.from_input
    normalize_calls = 0

    def count_normalization(context):
        nonlocal normalize_calls
        normalize_calls += 1
        return original_from_input(context)

    monkeypatch.setattr(
        PersistentMemoryContext,
        "from_input",
        staticmethod(count_normalization),
    )
    dependencies = MemoryCoordinator()
    resolver = Mock(wraps=dependencies._context_resolver)
    coordinator = MemoryCoordinator(context_resolver=resolver)
    request = InternalChatRequest(
        query="Continue the previous discussion.",
        memory_context=memory_context,
    )

    view = coordinator.prepare(request)

    resolver.resolve.assert_called_once()
    assert normalize_calls == 1
    normalized_context = resolver.resolve.call_args.args[0]
    assert isinstance(normalized_context, PersistentMemoryContext)
    assert view.context_artifact is not None
    assert "Earlier topic summary." in view.context_artifact.memory_brief
    assert view.has_prior_messages
    assert [message["role"] for message in view.history_for_model()] == [
        "system",
        "assistant",
    ]


def test_missing_context_is_empty_and_never_looks_up_session_id(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    resolver = Mock()
    coordinator = MemoryCoordinator(context_resolver=resolver)

    view = coordinator.prepare(ChatRequest(query="continue", session_id="same-chat"))

    resolver.resolve.assert_not_called()
    assert view.history == ()
    assert view.context_artifact is None
    assert not view.has_prior_messages


def test_disabled_persistent_memory_is_empty_even_when_request_has_context(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)
    resolver = Mock()
    coordinator = MemoryCoordinator(context_resolver=resolver)
    request = InternalChatRequest(
        query="question",
        memory_context=_memory_context(),
    )

    view = coordinator.prepare(request)

    resolver.resolve.assert_not_called()
    assert view.history == ()
    assert view.context_artifact is None
