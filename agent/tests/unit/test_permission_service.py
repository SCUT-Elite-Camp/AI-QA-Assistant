"""PermissionService fail-open 开关单元测试。

验证 get_accessible_doc_ids 在查询异常时的行为：
- PERMISSION_FAIL_OPEN=False（默认，fail-closed）-> 返回空列表（拒绝全部文档）
- PERMISSION_FAIL_OPEN=True（fail-open）-> 返回 None（不过滤）

通过 monkeypatch `_connect` 使其抛异常来模拟数据库故障。
"""

import sqlite3

import pytest

from agent.service.permission_service import PermissionService


@pytest.fixture
def service(monkeypatch):
    """构造一个不会真实连接数据库的 PermissionService。

    - is_admin 固定返回 False（普通用户路径，避免走 admin 分支）
    - _connect 抛异常（模拟权限库故障）
    """
    svc = PermissionService(db_path=":memory:")
    monkeypatch.setattr(svc, "is_admin", lambda user_id: False)

    def _broken_connect():
        raise sqlite3.Error("simulated db failure")

    monkeypatch.setattr(svc, "_connect", _broken_connect)
    return svc


@pytest.mark.no_storage
def test_fail_closed_returns_empty_list_by_default(service, monkeypatch):
    """默认（PERMISSION_FAIL_OPEN=False）在查询异常时应 fail-closed，返回空列表。"""
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "PERMISSION_FAIL_OPEN", False)

    result = service.get_accessible_doc_ids("user-1")
    assert result == []


@pytest.mark.no_storage
def test_fail_open_returns_none(service, monkeypatch):
    """PERMISSION_FAIL_OPEN=True 时在查询异常时应 fail-open，返回 None（不过滤）。"""
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "PERMISSION_FAIL_OPEN", True)

    result = service.get_accessible_doc_ids("user-1")
    assert result is None


@pytest.mark.no_storage
def test_admin_still_returns_none_regardless_of_fail_mode(service, monkeypatch):
    """管理员路径（is_admin=True）始终返回 None，不受 fail-open 开关影响。"""
    from agent.config.settings import settings

    monkeypatch.setattr(service, "is_admin", lambda user_id: True)
    monkeypatch.setattr(settings, "PERMISSION_FAIL_OPEN", False)

    result = service.get_accessible_doc_ids("admin-1")
    assert result is None


@pytest.mark.no_storage
def test_empty_user_id_returns_none(service, monkeypatch):
    """空 user_id 始终返回 None（不过滤），不触发数据库访问。"""
    from agent.config.settings import settings

    monkeypatch.setattr(settings, "PERMISSION_FAIL_OPEN", False)

    result = service.get_accessible_doc_ids("")
    assert result is None
