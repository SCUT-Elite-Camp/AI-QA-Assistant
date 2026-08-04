from collections import deque
from copy import deepcopy
from threading import RLock
from typing import Any

from agent.memory.base import ConversationMemory


class InMemoryConversationMemory(ConversationMemory):
    """Thread-safe, process-local CP2 short-term memory implementation."""

    ALLOWED_ROLES = {"system", "user", "assistant", "tool"}

    def __init__(self, max_messages: int = 10) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self.max_messages = max_messages
        self._sessions: dict[str, deque[dict[str, Any]]] = {}
        self._lock = RLock()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        key = self._normalize_session_id(session_id)
        with self._lock:
            return deepcopy(list(self._sessions.get(key, ())))

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        key = self._normalize_session_id(session_id)
        normalized_role = self._normalize_role(role)
        normalized_content = self._normalize_content(content)

        with self._lock:
            messages = self._sessions.setdefault(
                key,
                deque(maxlen=self.max_messages),
            )
            messages.append(
                {
                    "role": normalized_role,
                    "content": normalized_content,
                }
            )

    def clear(self, session_id: str) -> None:
        key = self._normalize_session_id(session_id)
        with self._lock:
            self._sessions.pop(key, None)

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must not be empty")
        return session_id.strip()

    @classmethod
    def _normalize_role(cls, role: str) -> str:
        normalized = role.strip().lower() if isinstance(role, str) else ""
        if normalized not in cls.ALLOWED_ROLES:
            allowed = ", ".join(sorted(cls.ALLOWED_ROLES))
            raise ValueError(f"role must be one of: {allowed}")
        return normalized

    @staticmethod
    def _normalize_content(content: str) -> str:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must not be empty")
        return content
