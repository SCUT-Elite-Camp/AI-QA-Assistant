from fastapi.testclient import TestClient

from app import app


def test_tools_api_returns_registry_metadata() -> None:
    client = TestClient(app)

    response = client.get("/api/tools")

    assert response.status_code == 200
    tools = response.json()
    assert tools
    assert set(tools[0]) == {"name", "description", "parameters", "enabled"}
    assert tools[0]["name"] == "search_documents"
    assert isinstance(tools[0]["description"], str)
    assert tools[0]["parameters"]["type"] == "object"
    assert tools[0]["enabled"] is True
