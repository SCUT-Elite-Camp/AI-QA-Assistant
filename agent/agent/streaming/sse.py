import json
from collections.abc import Iterator
from typing import Any

from agent.schemas.chat import ChatResponse


_TOKEN_CHUNK_SIZE = 32


def build_sse_event(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def chat_response_events(response: ChatResponse) -> Iterator[tuple[str, Any]]:
    """Adapt one completed ChatResponse to the shared demo SSE event contract."""
    yield "citations", [citation.model_dump() for citation in response.citations]

    if response.status != "success":
        yield "error", {"message": response.message or "Agent request failed"}
        return

    for offset in range(0, len(response.answer), _TOKEN_CHUNK_SIZE):
        yield "token", {"content": response.answer[offset:offset + _TOKEN_CHUNK_SIZE]}

    yield "done", {
        "trace_id": response.trace_id,
        "status": response.status,
        "citations_count": len(response.citations),
        "chat_title": response.chat_title,
    }
