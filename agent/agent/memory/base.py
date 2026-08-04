from abc import ABC, abstractmethod
from typing import Any


class ConversationMemory(ABC):
    """Public CP2 contract for session-scoped short-term conversation memory.

    ``get_messages`` returns OpenAI-compatible message dictionaries containing
    at least ``role`` and ``content``. Implementations must return defensive
    copies so callers cannot mutate stored history accidentally.
    """

    @abstractmethod
    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Return the retained messages for one session in chronological order."""
        raise NotImplementedError

    @abstractmethod
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append one message to a session and apply the retention limit."""
        raise NotImplementedError

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """Remove all retained messages for one session."""
        raise NotImplementedError
