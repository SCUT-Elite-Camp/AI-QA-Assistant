"""Agent 层权限服务。

查询 Web 层 SQLite 数据库，计算当前用户在 Milvus 中可访问的 doc_id 白名单。

设计要点：
- 不做缓存，每次检索实时查询（权限变更立即生效，无需重启或失效处理）。
- 管理员（users.role == 'admin'）返回 None，表示不过滤、可访问全部文档。
- 查询失败时的行为由 ``PERMISSION_FAIL_OPEN`` 配置控制：
  - False（默认，fail-closed）：返回空列表，拒绝全部文档访问，遵循最小权限。
  - True（fail-open）：返回 None（不过滤），供排查/降级时临时开启。
  故障始终记录 warning 日志。
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional

from agent.config.settings import settings
from agent.service.source_access import SourceAccessProvider, SourceAccessError

logger = logging.getLogger("agent-layer")

# 一次查询返回用户可访问文件的 doc_id：
#   1. 自己上传的文件（owner）
#   2. 全员共享的文件（visibility = 'shared'）
#   3. file_permissions 中显式授权的文件：
#      - grant_type = 'public'（全员）
#      - grant_type = 'user' 且 grant_id = 当前用户
#      - grant_type = 'department' 且 grant_id 属于当前用户所在部门
_ACCESSIBLE_DOC_IDS_SQL = """
SELECT DISTINCT f.doc_id
FROM files f
WHERE f.doc_id IS NOT NULL
  AND (
    f.user_id = ?
    OR f.visibility = 'shared'
    OR f.id IN (
      SELECT fp.file_id
      FROM file_permissions fp
      WHERE fp.grant_type = 'public'
         OR (fp.grant_type = 'user' AND fp.grant_id = ?)
         OR (
           fp.grant_type = 'department'
           AND fp.grant_id IN (
             SELECT ud.department_id
             FROM user_departments ud
             WHERE ud.user_id = ?
           )
         )
    )
  )
"""


class PermissionResolutionError(RuntimeError):
    """Strict authorization cannot establish an active, permitted actor."""

    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class PermissionService:
    """根据用户身份计算其可访问的 doc_id 列表。"""

    def __init__(self, db_path: Optional[str] = None, *, source_provider=None) -> None:
        self.db_path = db_path or settings.WEB_SQLITE_PATH
        self.source_provider = source_provider or SourceAccessProvider()

    @contextmanager
    def _connect(self):
        # sqlite3.Connection's own context manager commits but does not close.
        # Thousands of per-boundary reads must not retain connections/locks.
        connection = sqlite3.connect(self.db_path, timeout=5)
        try:
            yield connection
        finally:
            connection.close()

    def get_accessible_doc_ids_strict(self, user_id: str, *, doc_ids: Optional[list[str]] = None) -> list[str]:
        """Resolve Research ACL atomically; never honor the Chat fail-open flag.

        An unrestricted result is reserved for a known, enabled administrator.
        Actor validation and the document allowlist use the same live connection.
        """
        if not user_id or not user_id.strip():
            raise PermissionResolutionError("research_identity_required", 401)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT role, disabled FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if row is None or bool(row[1]):
                    raise PermissionResolutionError("research_actor_forbidden", 403)
                if row[0] == "admin":
                    ids = doc_ids if doc_ids is not None else self.source_provider.list_document_ids()
                else:
                    rows = conn.execute(
                        _ACCESSIBLE_DOC_IDS_SQL, (user_id, user_id, user_id)
                    ).fetchall()
                    ids = [str(item[0]) for item in rows if item[0]]
                    if doc_ids is not None:
                        ids = list(set(ids).intersection(doc_ids))
            return self.source_provider.filter_allowed(user_id, ids)
        except SourceAccessError as exc:
            raise PermissionResolutionError(exc.code, exc.status_code) from exc
        except PermissionResolutionError:
            raise
        except Exception as exc:
            logger.warning("[PERMISSION] strict Research ACL lookup failed: %s", type(exc).__name__)
            raise PermissionResolutionError("research_permission_unavailable", 503) from exc

    def is_admin(self, user_id: str) -> bool:
        """判断用户是否为管理员。查询失败时保守返回 False。"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT role FROM users WHERE id = ?", (user_id,)
                ).fetchone()
            return bool(row and row[0] == "admin")
        except Exception as exc:
            logger.warning(
                "[PERMISSION] failed to check admin role for user=%s: %s", user_id, exc
            )
            return False

    def get_accessible_doc_ids(self, user_id: str) -> Optional[list[str]]:
        """返回用户可访问的 doc_id 列表。

        返回 None 表示不过滤（管理员或配置为 fail-open 时的查询异常），
        返回空列表表示该用户当前没有任何可访问文件（或 fail-closed 时的查询异常）。
        """
        if not user_id:
            return None

        try:
            if self.is_admin(user_id):
                return None

            with self._connect() as conn:
                rows = conn.execute(
                    _ACCESSIBLE_DOC_IDS_SQL, (user_id, user_id, user_id)
                ).fetchall()

            return [row[0] for row in rows if row[0]]
        except Exception as exc:
            logger.warning(
                "[PERMISSION] failed to resolve accessible doc_ids for user=%s: %s",
                user_id,
                exc,
            )
            # fail-open（返回 None）仅在 PERMISSION_FAIL_OPEN=true 时允许，
            # 默认 fail-closed（返回空列表），避免权限服务故障时权限全开。
            if settings.PERMISSION_FAIL_OPEN:
                return None
            return []
