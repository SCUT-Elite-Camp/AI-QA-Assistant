import json

import pytest
from fastapi.testclient import TestClient

from app import app


def test_health_endpoint_for_web_smoke() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_retrieval_preload() -> None:
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("status", "retrieval_ready", "intent_ready", "detail")} == {
        "status": "ready",
        "retrieval_ready": True,
        "intent_ready": True,
        "detail": "",
    }


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
    assert set(body.keys()) >= {
        "trace_id",
        "status",
        "answer",
        "message",
        "citations",
        "chat_title",
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
    assert {key: body[key] for key in ("trace_id", "status", "answer", "message", "citations", "chat_title")} == {
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


@pytest.mark.parametrize("weight_mode", ["fast", "thinking", "auto"])
def test_sse_stream_endpoint_matches_canonical_chat_response(weight_mode: str) -> None:
    client = TestClient(app)
    request = {
        "query": "项目 Q1 阶段需要完成哪些功能？",
        "weight_mode": weight_mode,
    }

    json_response = client.post("/api/chat", json=request)
    assert json_response.status_code == 200
    json_body = json_response.json()

    response = client.post("/api/chat/stream", json=request)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events: list[tuple[str, object]] = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) == 2 and lines[0].startswith("event: ") and lines[1].startswith("data: "):
            events.append((lines[0][7:], json.loads(lines[1][6:])))

    citations = next(data for name, data in events if name == "citations")
    answer = "".join(
        data["content"] for name, data in events if name == "token"
    )
    done = next(data for name, data in events if name == "done")

    assert [name for name, _ in events if name in {"citations", "done", "error"}] == [
        "citations",
        "done",
    ]
    assert citations == json_body["citations"]
    assert answer == json_body["answer"]
    assert done["status"] == json_body["status"] == "success"
    assert done["citations_count"] == len(json_body["citations"])
    assert done["chat_title"] == json_body["chat_title"]
