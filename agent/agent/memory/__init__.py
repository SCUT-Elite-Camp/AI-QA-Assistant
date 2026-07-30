from agent.config.settings import settings
from agent.memory.base import ConversationMemory
from agent.memory.conversation_memory import InMemoryConversationMemory

_default_memory = InMemoryConversationMemory(
    max_messages=settings.MAX_MEMORY_MESSAGES,
)


def get_default_memory() -> ConversationMemory:
    """Return the process-wide memory shared by request-scoped Agent objects."""

    return _default_memory


__all__ = [
    "ConversationMemory",
    "InMemoryConversationMemory",
    "get_default_memory",
]
