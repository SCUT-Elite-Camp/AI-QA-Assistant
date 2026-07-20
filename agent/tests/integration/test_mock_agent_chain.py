from fastapi.testclient import TestClient

from app import app


def test_mock_agent_chain_api_success() -> None:
    client = TestClient(app)

    response = client.post("/api/chat", json={"query": "项目 Q1 阶段需要完成哪些功能？"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["trace_id"].startswith("trace-")
    assert body["citations"]

