from fastapi.testclient import TestClient

from app import app


def test_health_endpoint_for_web_smoke() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_response_has_web_required_fields() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "query": "项目 Q1 阶段需要完成哪些功能？",
            "top_k": 3,
            "retrieval_mode": "hybrid",
            "stream": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "trace_id", "status", "answer", "message", "citations", "chat_title",
    }
    assert body["status"] == "success"
    assert body["trace_id"].startswith("trace-")
    assert isinstance(body["citations"], list)
    assert {"citation_id", "title", "doc_id", "chunk_id", "score", "snippet"}.issubset(
        body["citations"][0].keys()
    )


def test_chat_error_response_keeps_web_contract() -> None:
    client = TestClient(app)

    response = client.post("/api/chat", json={"query": "   "})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "trace_id": body["trace_id"],
        "status": "invalid_query",
        "answer": "",
        "message": "请输入有效问题。",
        "citations": [],
        "chat_title": None,
    }


def test_cors_preflight_for_web() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_sse_stream_endpoint_emits_expected_events() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/chat/stream",
        json={"query": "项目 Q1 阶段需要完成哪些功能？", "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: token" in body
    assert "event: citations" in body
    assert "event: done" in body
    assert '"status": "success"' in body
