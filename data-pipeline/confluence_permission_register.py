"""
Confluence 文档权限登记器。

用途：
  在 confluence_pull.py 把某个页面/附件写入 Milvus 之后，将同一文档登记到
  Web 层 SQLite（web/.data/sqlite.db）的 files / file_permissions 表，从而使
  Agent 层的 doc_id 白名单权限过滤（permission_service.get_accessible_doc_ids）
  对 Confluence 来源文档生效，实现「空间级权限隔离」。

空间级隔离原理：
  Confluence 页面没有独立权限，权限完全继承其所属空间（Space）的权限方案。
  因此我们只需把「空间 → 系统可见范围」的映射写成配置文件
  （confluence_space_permissions.json），入库时按空间登记即可。

映射配置支持三种可见范围：
  - visibility = "shared"              → 全员共享（等价空间对所有人公开）
  - grants 含 {"type":"public"}        → file_permissions.grant_type='public'
  - grants 含 {"type":"department", "grant_id":<deptId>} → 仅该部门可见
  - grants 含 {"type":"user", "grant_id":<userId>}       → 仅该用户可见

设计要点：
  - 幂等：files.doc_id 唯一索引，重复登记同一 doc 时 UPDATE 而非重复插入。
  - 健壮：owner 用户在 users 表不存在时自动补建（否则违反外键约束）。
  - 非阻断：登记失败只记 warning，不影响 Confluence 入库主流程。
"""

import json
import logging
import os
import sqlite3
import uuid
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_DB_PATH = os.path.join(REPO, "web", ".data", "sqlite.db")
CONFIG_PATH = os.path.join(HERE, "confluence_space_permissions.json")

logger = logging.getLogger("confluence_permission_register")


# ───────────────────────────── 配置加载 ─────────────────────────────

def load_config(config_path: Optional[str] = None) -> dict:
    """加载空间权限映射配置；文件缺失或格式非法时返回空映射（保守：全部不可见）。"""
    path = config_path or CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是 JSON 对象")
        return data
    except Exception as exc:
        logger.warning("[CONF-PERM] 加载空间权限映射失败 (%s)：%s", path, exc)
        return {}


def resolve_space_policy(config: dict, space_key: str) -> dict:
    """解析某个空间的实际可见范围策略。

    优先级：空间显式配置 > defaults > 内置保守默认（private，仅 owner 可见）。
    """
    spaces = config.get("spaces", {}) if isinstance(config, dict) else {}
    defaults = config.get("defaults", {}) if isinstance(config, dict) else {}

    policy: dict = {
        "visibility": "private",
        "owner_user_id": "demo-admin",
        "grants": [],
    }

    if isinstance(defaults, dict):
        policy.update({
            k: defaults.get(k, policy[k])
            for k in ("visibility", "owner_user_id")
        })

    space_cfg = spaces.get(space_key) if isinstance(spaces, dict) else None
    if isinstance(space_cfg, dict):
        policy.update({
            k: space_cfg.get(k, policy[k])
            for k in ("visibility", "owner_user_id")
        })
        if "grants" in space_cfg and isinstance(space_cfg["grants"], list):
            policy["grants"] = space_cfg["grants"]

    return policy


# ───────────────────────────── 用户兜底 ─────────────────────────────

def ensure_user(conn: sqlite3.Connection, user_id: str) -> bool:
    """确保 owner 用户在 users 表存在，不存在则自动补建一条记录。

    users 表有多个 NOT NULL 字段，故用合理默认值插入。
    返回是否成功（存在 / 插入成功）。
    """
    if not user_id:
        return False
    row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, email, name, avatar, username, provider, provider_id, role, disabled)
            VALUES (?, ?, ?, ?, ?, 'sso', ?, 'user', 0)
            """,
            (
                user_id,
                f"{user_id}@confluence.local",
                user_id,
                "",
                user_id,
                user_id,
            ),
        )
        return True
    except Exception as exc:
        logger.warning("[CONF-PERM] 补建 owner 用户 %s 失败: %s", user_id, exc)
        return False


# ───────────────────────────── 核心登记 ─────────────────────────────

def register_doc_permissions(
    doc_id: str,
    title: str,
    source_url: str,
    space_key: str,
    db_path: Optional[str] = None,
    config: Optional[dict] = None,
    size: int = 0,
) -> bool:
    """将单个 Confluence 文档登记到 Web 层 files/file_permissions 表。

    返回 True 表示登记成功；False 表示失败（记录 warning，不抛出，避免阻断主流程）。

    参数：
      doc_id      向量库中的 doc_id（即 Document.doc_id）
      title       文档标题（页面标题）
      source_url  页面完整链接
      space_key   Confluence 空间 Key
      db_path     Web 层 SQLite 路径，默认 web/.data/sqlite.db
      config      空间权限映射配置（None 则自动加载）
      size        文档字节数（Confluence 无真实字节，可用 0 或字符数）
    """
    if not doc_id:
        logger.warning("[CONF-PERM] 跳过空 doc_id 的权限登记")
        return False

    policy = resolve_space_policy(config if config is not None else load_config(), space_key)
    owner = policy.get("owner_user_id") or "demo-admin"
    visibility = policy.get("visibility") or "private"
    grants = policy.get("grants") or []
    db = db_path or DEFAULT_DB_PATH

    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row

            # 1. 确保 owner 用户存在（外键约束）
            if not ensure_user(conn, owner):
                logger.warning("[CONF-PERM] owner 用户不可用（%s），跳过登记 doc=%s", owner, doc_id)
                return False

            # 2. 幂等 upsert files 记录（doc_id 唯一）
            conn.execute(
                """
                INSERT INTO files
                    (id, user_id, name, original_name, mime_type, size,
                     storage_path, visibility, doc_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    name = excluded.name,
                    original_name = excluded.original_name,
                    visibility = excluded.visibility,
                    storage_path = excluded.storage_path,
                    user_id = excluded.user_id,
                    size = excluded.size
                """,
                (
                    str(uuid.uuid4()),
                    owner,
                    title,
                    title,
                    "text/markdown",
                    size,
                    f"confluence://{space_key}/{doc_id}",
                    visibility,
                    doc_id,
                    int(__import__("time").time()),
                ),
            )

            file_row = conn.execute(
                "SELECT id FROM files WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if not file_row:
                logger.warning("[CONF-PERM] upsert 后仍找不到 files 记录，跳过 doc=%s", doc_id)
                return False
            file_id = file_row["id"]

            # 3. 先清空旧授权，再按当前策略重写
            conn.execute(
                "DELETE FROM file_permissions WHERE file_id = ?", (file_id,)
            )
            grant_seq = 0
            for g in grants:
                if not isinstance(g, dict):
                    continue
                gtype = g.get("type")
                gid = g.get("grant_id")
                if gtype == "public":
                    gid = None
                if gtype not in ("user", "department", "public"):
                    logger.warning("[CONF-PERM] 忽略未知 grant_type=%s", gtype)
                    continue
                conn.execute(
                    """
                    INSERT INTO file_permissions
                        (id, file_id, grant_type, grant_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        file_id,
                        gtype,
                        gid,
                        int(__import__("time").time()),
                    ),
                )
                grant_seq += 1

            # 4. 如果 visibility=shared 但没有任何 grant，无需额外授权（shared 已全员可见）
            logger.info(
                "[CONF-PERM] 已登记 doc=%s space=%s visibility=%s grants=%d",
                doc_id[:12], space_key, visibility, grant_seq,
            )
            return True

    except Exception as exc:
        logger.warning("[CONF-PERM] 登记 doc=%s 失败: %s", doc_id, exc)
        return False
