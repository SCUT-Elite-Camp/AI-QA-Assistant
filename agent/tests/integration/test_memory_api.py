from fastapi.testclient import TestClient

from app import app
from agent.api.chat_routes import get_agent
from agent.config.settings import settings


def test_internal_reset_memory_api_purges_session(monkeypatch) -> None:
    client = TestClient(app)
    # Access the agent memory instance
    agent = get_agent()
    session_id = "test-delete-session-123"

    # Pre-populate memory
    agent.memory.add_message(session_id, "user", "Hello")
    agent.memory.add_message(session_id, "assistant", "Hi there")
    assert len(agent.memory.get_messages(session_id)) == 2

    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "test-internal-token")

    # The legacy public reset endpoint was removed; only the token-protected
    # BFF endpoint can clear process-local compatibility memory.
    public_response = client.delete(f"/api/chat/memory/{session_id}")
    assert public_response.status_code == 404

    missing_token = client.post(
        "/api/internal/memory/reset-short-window",
        json={"chat_id": session_id},
    )
    wrong_token = client.post(
        "/api/internal/memory/reset-short-window",
        headers={"X-Agent-Internal-Token": "wrong-token"},
        json={"chat_id": session_id},
    )
    assert missing_token.status_code == 403
    assert wrong_token.status_code == 403
    assert len(agent.memory.get_messages(session_id)) == 2

    response = client.post(
        "/api/internal/memory/reset-short-window",
        headers={"X-Agent-Internal-Token": "test-internal-token"},
        json={"chat_id": session_id},
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "ok"

    # Verify memory is cleared
    assert agent.memory.get_messages(session_id) == []
