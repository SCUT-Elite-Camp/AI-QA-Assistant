# ConversationMemory Public Contract (CP2)

## 1. Ownership and Purpose

This contract is maintained by Workstream 1 and consumed by Query
Understanding, Agent Runner, and Chat orchestration.

The implementation is located at:

- `agent/memory/base.py`: stable public interface;
- `agent/memory/conversation_memory.py`: CP2 in-process implementation;
- `agent/memory/__init__.py`: process-level default instance.

## 2. Stable Interface

```python
from abc import ABC, abstractmethod
from typing import Any


class ConversationMemory(ABC):
    @abstractmethod
    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        ...

    @abstractmethod
    def clear(self, session_id: str) -> None:
        ...
```

Usage:

```python
from agent.memory import get_default_memory

memory = get_default_memory()
history = memory.get_messages(session_id)
memory.add_message(session_id, "user", query)
memory.add_message(session_id, "assistant", answer)
memory.clear(session_id)
```

## 3. Behavioral Requirements

- `session_id` must be a non-empty string.
- Messages from different sessions must be strictly isolated.
- Messages are returned in chronological order.
- Each message contains at least `role` and `content` and can be passed directly
  to the LLM.
- Allowed roles are `system`, `user`, `assistant`, and `tool`.
- `get_messages` returns a deep copy so callers cannot mutate stored history.
- Each session retains at most `MAX_MEMORY_MESSAGES`; the oldest messages are
  removed when the limit is exceeded.
- Clearing a nonexistent session is idempotent.
- If `ChatRequest.session_id` is empty, the Agent does not read or write memory.
- If `MEMORY_ENABLED=false`, Chat orchestration skips all memory operations.

## 4. Clarification Flow

When `QueryPlan.needs_clarification=true`:

1. Agent Runner does not call the answer LLM or any tools.
2. Chat returns `clarification_required`.
3. If a `session_id` exists, Chat orchestration stores the current original
   user query and the Agent's clarification question.
4. Query Understanding may identify the next user message in the same session
   as `is_clarification_reply=true`.

Query Understanding uses history as read-only input. It must not write messages
during rewriting. Chat orchestration performs the single authoritative write
after a user-visible result is available, preventing duplicated messages.

## 5. Lifecycle and Concurrency Boundary

`InMemoryConversationMemory` uses a lock for thread-safe access within one
process. All request-level `Agent` instances in that process share the default
instance.

The current implementation is not persistent across processes or restarts. A
Redis or database implementation must be added when multiple workers or durable
history are required, while continuing to satisfy this interface. Agent Runner
must not connect directly to storage.

## 6. Configuration

```env
MEMORY_ENABLED=true
MAX_MEMORY_MESSAGES=10
```

## 7. Minimum Acceptance Criteria

- A session reads previous user and assistant messages in order.
- Different sessions never leak messages.
- Only the newest messages remain after the limit is exceeded.
- Requests without `session_id` have no memory side effects.
- Clarification questions are stored and clarification turns do not call
  retrieval tools.
