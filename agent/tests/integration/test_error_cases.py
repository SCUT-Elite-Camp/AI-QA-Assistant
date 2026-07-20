from fastapi.testclient import TestClient

from app import app


def test_chat_api_invalid_query() -> None:
    client = TestClient(app)

    response = client.post("/api/chat", json={"query": "   "})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid_query"
    assert body["answer"] == ""

