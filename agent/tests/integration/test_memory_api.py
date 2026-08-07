from fastapi.testclient import TestClient

from app import app
from agent.api.chat_routes import get_agent


def test_clear_memory_api_purges_session() -> None:
    client = TestClient(app)
    # Access the agent memory instance
    agent = get_agent()
    session_id = "test-delete-session-123"

    # Pre-populate memory
    agent.memory.add_message(session_id, "user", "Hello")
    agent.memory.add_message(session_id, "assistant", "Hi there")
    assert len(agent.memory.get_messages(session_id)) == 2

    # Call DELETE /api/chat/memory/{session_id}
    response = client.delete(f"/api/chat/memory/{session_id}")

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "ok"
    assert res_data["session_id"] == session_id

    # Verify memory is cleared
    assert agent.memory.get_messages(session_id) == []
