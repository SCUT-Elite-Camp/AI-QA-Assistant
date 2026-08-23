from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import app as production_app
from agent.api.chat_routes import get_agent, router as public_chat_router
from agent.api.internal_memory_routes import router as internal_memory_router
from agent.config.settings import settings
from agent.schemas.chat import ChatRequest, ChatResponse, MemoryDecision


@dataclass
class RecordingMemory:
    cleared_chat_ids: list[str] = field(default_factory=list)

    def clear(self, chat_id: str) -> None:
        self.cleared_chat_ids.append(chat_id)


@dataclass
class RecordingAgent:
    memory: RecordingMemory = field(default_factory=RecordingMemory)
    requests: list[ChatRequest] = field(default_factory=list)

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            trace_id="trace-internal-memory",
            status="success",
            answer="A controlled answer.",
            message="",
            citations=[],
        )

    def chat_with_memory(
        self,
        request: ChatRequest,
    ) -> tuple[ChatResponse, MemoryDecision]:
        return self.chat(request), MemoryDecision(fact_proposals=[])


@pytest.fixture
def internal_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, RecordingAgent]:
    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)

    application = FastAPI()
    application.include_router(public_chat_router, prefix="/api")
    application.include_router(internal_memory_router, prefix="/api/internal")
    agent = RecordingAgent()
    application.dependency_overrides[get_agent] = lambda: agent
    return TestClient(application), agent


def _headers(token: str = "internal-token") -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Agent-Internal-Token": token,
    }


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
        "facts": [],
        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 1,
                "role": "assistant",
                "content": "Earlier answer.",
            }
        ],
    }


def _internal_chat_payload() -> dict[str, object]:
    return {
        "query": "What did we discuss?",
        "session_id": "chat-1",
        "memory_context": _memory_context(),
    }


def _compaction_payload() -> dict[str, object]:
    return {
        "actor": {"user_id": "user-1", "authenticated": True},
        "chat_id": "chat-1",
        "revision": 1,
        "active_snapshot": None,
        "messages": [],
        "tail_size": 8,
        "min_coverable_messages": 12,
        "soft_token_budget": 1000,
    }


def _compaction_messages(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"message-{sequence}",
            "sequence": sequence,
            "revision": 1,
            "role": "user" if sequence % 2 else "assistant",
            "content": f"persisted message {sequence}",
        }
        for sequence in range(1, count + 1)
    ]


def test_production_application_registers_only_the_private_memory_routes() -> None:
    assert str(production_app.url_path_for("internal_chat")) == "/api/internal/chat"
    assert (
        str(production_app.url_path_for("compaction_plan"))
        == "/api/internal/memory/compaction-plan"
    )
    assert (
        str(production_app.url_path_for("reset_short_window"))
        == "/api/internal/memory/reset-short-window"
    )


def test_internal_endpoints_reject_missing_and_invalid_tokens(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    missing = client.post("/api/internal/chat", json=_internal_chat_payload())
    invalid = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers("wrong-token"),
    )

    assert missing.status_code == invalid.status_code == 403
    assert missing.json() == invalid.json() == {"detail": "forbidden"}
    assert agent.requests == []


def test_internal_authentication_precedes_request_body_validation(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, _ = internal_client

    response = client.post("/api/internal/chat", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_internal_endpoints_require_json_content_type(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    response = client.post(
        "/api/internal/memory/reset-short-window",
        content='{"chat_id":"chat-1"}',
        headers={
            "Content-Type": "text/plain",
            "X-Agent-Internal-Token": "internal-token",
        },
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "unsupported_media_type"}
    assert agent.memory.cleared_chat_ids == []


def test_public_chat_rejects_internal_memory_context(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, _ = internal_client

    response = client.post("/api/chat", json=_internal_chat_payload())

    assert response.status_code == 422
    assert "memory_context" in response.text


def test_internal_chat_returns_fixed_409_when_persistent_memory_is_disabled(
    internal_client: tuple[TestClient, RecordingAgent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, agent = internal_client
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)

    response = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {"code": "persistent_memory_disabled"}
    assert agent.requests == []


def test_internal_chat_uses_shared_agent_and_returns_empty_fact_proposals(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    response = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["response"]["trace_id"] == "trace-internal-memory"
    assert response.json()["memory_decision"]["fact_proposals"] == []
    assert len(agent.requests) == 1


def test_internal_chat_rejects_memory_context_revision_mismatch(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _internal_chat_payload()
    payload["memory_context"]["snapshot"]["revision"] = 2

    response = client.post(
        "/api/internal/chat",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_memory_context"}
    assert agent.requests == []


def test_compaction_is_a_noop_and_reset_clears_only_short_window(
    internal_client: tuple[TestClient, RecordingAgent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, agent = internal_client
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)

    compaction = client.post(
        "/api/internal/memory/compaction-plan",
        json=_compaction_payload(),
        headers=_headers(),
    )
    reset = client.post(
        "/api/internal/memory/reset-short-window",
        json={"chat_id": "chat-1"},
        headers=_headers(),
    )

    assert compaction.status_code == 200
    assert compaction.json() == {"should_compact": False}
    assert reset.status_code == 200
    assert reset.json() == {"status": "ok"}
    assert agent.memory.cleared_chat_ids == ["chat-1"]
    assert agent.requests == []


def test_compaction_returns_a_pure_plan_without_using_the_shared_agent(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _compaction_payload()
    payload["messages"] = _compaction_messages(20)

    response = client.post(
        "/api/internal/memory/compaction-plan",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "should_compact": True,
        "expected_active_snapshot": None,
        "new_snapshot": {
            "covered_from_sequence": 1,
            "covered_to_sequence": 12,
            "covered_from_message_id": "message-1",
            "covered_to_message_id": "message-12",
            "summary": "[New covered messages]\n"
            "- user: persisted message 1\n"
            "- assistant: persisted message 2\n"
            "- user: persisted message 3\n"
            "- assistant: persisted message 4\n"
            "- user: persisted message 5\n"
            "- assistant: persisted message 6\n"
            "- user: persisted message 7\n"
            "- assistant: persisted message 8\n"
            "- user: persisted message 9\n"
            "- assistant: persisted message 10\n"
            "- user: persisted message 11\n"
            "- assistant: persisted message 12",
        },
    }
    assert agent.requests == []
    assert agent.memory.cleared_chat_ids == []


def test_compaction_rejects_non_current_revision_messages(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _compaction_payload()
    payload["messages"] = [
        {
            "id": "message-1",
            "sequence": 1,
            "revision": 2,
            "role": "user",
            "content": "stale revision",
        }
    ]

    response = client.post(
        "/api/internal/memory/compaction-plan",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_memory_context"}
    assert agent.requests == []
