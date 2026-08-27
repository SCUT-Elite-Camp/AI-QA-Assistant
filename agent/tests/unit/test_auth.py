"""Agent 层接口认证单元测试。

覆盖 verify_agent_key 依赖的四种场景：
- AGENT_API_KEY 未配置 -> 503
- 缺少 Authorization 头 -> 401
- 提供错误密钥 -> 401
- 提供正确密钥 -> 200
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agent.auth import verify_agent_key


@pytest.fixture
def app():
    """构造一个挂载 verify_agent_key 的最小 FastAPI 应用。"""
    application = FastAPI()

    @application.get("/secured")
    def secured(_: None = Depends(verify_agent_key)):
        return {"ok": True}

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.mark.no_storage
def test_missing_key_returns_503(client, monkeypatch):
    """未配置 AGENT_API_KEY 时应显式拒绝服务（503），而非静默放行。"""
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "AGENT_API_KEY", "")

    resp = client.get("/secured", headers={"Authorization": "Bearer whatever"})
    assert resp.status_code == 503


@pytest.mark.no_storage
def test_missing_authorization_header_returns_401(client, monkeypatch):
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "AGENT_API_KEY", "test-secret-123")

    resp = client.get("/secured")
    assert resp.status_code == 401


@pytest.mark.no_storage
def test_invalid_key_returns_401(client, monkeypatch):
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "AGENT_API_KEY", "test-secret-123")

    resp = client.get("/secured", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


@pytest.mark.no_storage
def test_valid_key_returns_200(client, monkeypatch):
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "AGENT_API_KEY", "test-secret-123")

    resp = client.get("/secured", headers={"Authorization": "Bearer test-secret-123"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

