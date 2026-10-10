from fastapi.testclient import TestClient

from app import app


def test_public_reset_route_is_not_exposed() -> None:
    client = TestClient(app)

    response = client.delete("/api/chat/memory/test-delete-session-123")

    assert response.status_code == 404
