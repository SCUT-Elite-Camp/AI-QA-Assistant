from fastapi.testclient import TestClient

from app import app
from agent.api.chat_routes import get_agent
from agent.config.settings import settings
from agent.schemas.chat import ChatResponse


class StubAgent:
    def __init__(self) -> None:
        self.memory = type("Memory", (), {"clear": lambda _self, _chat_id: None})()

    def chat(self, _request):
        return ChatResponse(
            trace_id="trace-internal",
            status="success",
            answer="Answer.",
            message="",
            citations=[],
        )


def memory_context() -> dict:
    return {
        "actor": {"user_id": "user-a", "authenticated": True},
        "chat_id": "chat-a",
        "revision": 1,
        "current_message_id": "message-2",
        "current_sequence": 2,
        "snapshot": None,
        "facts": [],
        "tail": [
            {
                "id": "message-1",
                "sequence": 1,
                "revision": 1,
                "role": "user",
                "content": "Earlier question",
            }
        ],
    }


def compaction_request(messages: list[dict] | None = None) -> dict:
    return {
        "actor": memory_context()["actor"],
        "chat_id": "chat-a",
        "revision": 1,
        "active_snapshot": None,
        "messages": messages or [],
        "tail_size": 8,
        "min_coverable_messages": 12,
        "soft_token_budget": 1000,
    }


def test_internal_memory_endpoints_require_token_and_preserve_public_boundary(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    app.dependency_overrides[get_agent] = StubAgent
    client = TestClient(app)
    try:
        request = {"query": "Question", "memory_context": memory_context()}
        assert client.post("/api/internal/chat", json=request).status_code == 403
        assert client.post(
            "/api/internal/chat",
            headers={"X-Agent-Internal-Token": "wrong-token"},
            json=request,
        ).status_code == 403

        public_response = client.post("/api/chat", json=request)
        assert public_response.status_code == 422

        response = client.post(
            "/api/internal/chat",
            headers={"X-Agent-Internal-Token": "test-internal-token"},
            json=request,
        )
        assert response.status_code == 200
        assert set(response.json()) == {"response", "memory_decision"}
        assert response.json()["response"]["answer"] == "Answer."

        plan = client.post(
            "/api/internal/memory/compaction-plan",
            headers={"X-Agent-Internal-Token": "test-internal-token"},
            json=compaction_request(),
        )
        assert plan.status_code == 200
        assert plan.json() == {"should_compact": False}
    finally:
        app.dependency_overrides.clear()


def test_internal_compaction_plan_is_deterministic_and_contains_only_data(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    client = TestClient(app)
    messages = [
        {
            "id": f"message-{sequence}",
            "sequence": sequence,
            "revision": 1,
            "role": "assistant",
            "content": f"message {sequence}",
        }
        for sequence in range(1, 21)
    ]

    response = client.post(
        "/api/internal/memory/compaction-plan",
        headers={"X-Agent-Internal-Token": "test-internal-token"},
        json=compaction_request(messages),
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
            + "\n".join(f"- assistant: message {sequence}" for sequence in range(1, 13)),
        },
    }


def test_internal_chat_returns_fixed_409_when_persistent_memory_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)
    client = TestClient(app)
    response = client.post(
        "/api/internal/chat",
        headers={"X-Agent-Internal-Token": "test-internal-token"},
        json={"query": "Question", "memory_context": memory_context()},
    )
    assert response.status_code == 409
    assert response.json() == {"code": "persistent_memory_disabled"}

    compaction = client.post(
        "/api/internal/memory/compaction-plan",
        headers={"X-Agent-Internal-Token": "test-internal-token"},
        json=compaction_request(),
    )
    assert compaction.status_code == 409
    assert compaction.json() == {"code": "persistent_memory_disabled"}
