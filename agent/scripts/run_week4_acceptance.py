import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app


def main() -> None:
    client = TestClient(app)

    checks = [
        ("health", client.get("/health")),
        (
            "chat_success",
            client.post("/api/chat", json={"query": "项目 Q1 阶段需要完成哪些功能？"}),
        ),
        ("chat_invalid_query", client.post("/api/chat", json={"query": "   "})),
        (
            "chat_stream",
            client.post("/api/chat/stream", json={"query": "项目 Q1 阶段需要完成哪些功能？", "stream": True}),
        ),
    ]

    for name, response in checks:
        print(f"{name}: http={response.status_code}")
        if response.headers.get("content-type", "").startswith("application/json"):
            print(response.json())
        else:
            print(response.text[:300])

    assert checks[0][1].json() == {"status": "ok"}
    assert checks[1][1].json()["status"] == "success"
    assert checks[2][1].json()["status"] == "invalid_query"
    assert "event: done" in checks[3][1].text
    print("week4_acceptance: passed")


if __name__ == "__main__":
    main()
