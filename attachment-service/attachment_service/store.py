from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class AttachmentStore:
    STATUS_TRANSITIONS = {
        "uploading": {"scanning", "failed", "expired", "deleted"},
        "scanning": {"parsing", "failed", "quarantined", "expired", "deleted"},
        "parsing": {"chunking", "ready", "needs_review", "failed", "expired", "deleted"},
        "chunking": {"parsing", "embedding", "failed", "expired", "deleted"},
        "embedding": {"parsing", "indexing", "failed", "expired", "deleted"},
        "indexing": {"parsing", "ready", "failed", "expired", "deleted"},
        "ready": {"parsing", "expired", "deleted"},
        "needs_review": {"parsing", "ready", "expired", "deleted"},
        "failed": {"parsing", "expired", "deleted"},
        "quarantined": {"deleted"},
        "expired": {"deleted"},
        "deleted": set(),
    }
    VISION_TRANSITIONS = {
        "not_requested": {"queued"},
        "queued": {"running", "failed"},
        "running": {"ready", "failed"},
        "ready": {"queued"},
        "failed": {"queued"},
    }
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        self._local = threading.local()
        self._initialize()

    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.database, timeout=30, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._local.connection = connection
        return connection

    def _initialize(self) -> None:
        db = self.connection()
        db.executescript("""
        CREATE TABLE IF NOT EXISTS attachments (
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, mime_type TEXT NOT NULL,
          extension TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
          owner_id TEXT NOT NULL, dedupe_domain TEXT NOT NULL, scope TEXT NOT NULL,
          status TEXT NOT NULL, vision_status TEXT NOT NULL DEFAULT 'not_requested',
          blob_path TEXT NOT NULL, key_id TEXT NOT NULL, created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, expires_at INTEGER, error_code TEXT NOT NULL DEFAULT '',
          evidence_version INTEGER NOT NULL DEFAULT 1, deleted_at INTEGER,
          knowledge_base_id TEXT, document_id TEXT, version_id TEXT,
          source_scope TEXT, active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS blobs (
          storage_key TEXT PRIMARY KEY, dedupe_domain TEXT NOT NULL, sha256 TEXT NOT NULL,
          blob_path TEXT NOT NULL, key_id TEXT NOT NULL, ref_count INTEGER NOT NULL,
          created_at INTEGER NOT NULL, UNIQUE(dedupe_domain, sha256)
        );
        CREATE INDEX IF NOT EXISTS attachments_expiry_idx ON attachments(expires_at, status);
        CREATE INDEX IF NOT EXISTS attachments_domain_sha_idx ON attachments(dedupe_domain, sha256);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          payload TEXT NOT NULL DEFAULT '{}', error_code TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS evidence (
          id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, source_type TEXT NOT NULL,
          original_content TEXT NOT NULL, current_content TEXT NOT NULL,
          locator TEXT NOT NULL DEFAULT '{}', confidence REAL,
          parser TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
          confirmed INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS evidence_attachment_idx ON evidence(attachment_id, version);
        CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
          evidence_id UNINDEXED, attachment_id UNINDEXED, content,
          tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS evidence_revisions (
          id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, attachment_id TEXT NOT NULL,
          previous_content TEXT NOT NULL, corrected_content TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL,
          from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, created_at INTEGER NOT NULL,
          FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS derivatives (
          id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, kind TEXT NOT NULL,
          locator TEXT NOT NULL DEFAULT '{}', mime_type TEXT NOT NULL,
          blob_path TEXT NOT NULL, key_id TEXT NOT NULL, created_at INTEGER NOT NULL,
          FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS derivatives_attachment_idx ON derivatives(attachment_id, kind);
        """)
        existing = {
            str(row[1]) for row in db.execute("PRAGMA table_info(attachments)").fetchall()
        }
        for column, declaration in (
            ("knowledge_base_id", "TEXT"),
            ("document_id", "TEXT"),
            ("version_id", "TEXT"),
            ("source_scope", "TEXT"),
            ("active", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in existing:
                db.execute(f"ALTER TABLE attachments ADD COLUMN {column} {declaration}")
        db.execute(
            "CREATE INDEX IF NOT EXISTS attachments_library_scope_idx "
            "ON attachments(owner_id, knowledge_base_id, source_scope, active, status)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS attachments_library_document_idx "
            "ON attachments(document_id, version_id)"
        )
        db.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (int(time.time()),))
        db.execute(
            "UPDATE attachments SET vision_status='failed', updated_at=? "
            "WHERE vision_status='running'",
            (int(time.time()),),
        )
        db.commit()

    def get_blob(self, dedupe_domain: str, sha256: str) -> dict[str, Any] | None:
        row = self.connection().execute(
            "SELECT * FROM blobs WHERE dedupe_domain=? AND sha256=?",
            (dedupe_domain, sha256),
        ).fetchone()
        return dict(row) if row else None

    def acquire_blob(self, storage_key: str, dedupe_domain: str, sha256: str, blob_path: str, key_id: str) -> dict[str, Any]:
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM blobs WHERE dedupe_domain=? AND sha256=?", (dedupe_domain, sha256)).fetchone()
        if row:
            db.execute("UPDATE blobs SET ref_count=ref_count+1 WHERE storage_key=?", (row["storage_key"],))
            db.commit()
            return dict(row)
        now = int(time.time())
        db.execute("INSERT INTO blobs VALUES(?,?,?,?,?,?,?)", (storage_key, dedupe_domain, sha256, blob_path, key_id, 1, now))
        db.commit()
        return {"storage_key": storage_key, "dedupe_domain": dedupe_domain, "sha256": sha256, "blob_path": blob_path, "key_id": key_id, "ref_count": 1, "created_at": now}

    def release_blob(self, dedupe_domain: str, sha256: str) -> str | None:
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM blobs WHERE dedupe_domain=? AND sha256=?", (dedupe_domain, sha256)).fetchone()
        if not row:
            db.commit()
            return None
        if row["ref_count"] > 1:
            db.execute("UPDATE blobs SET ref_count=ref_count-1 WHERE storage_key=?", (row["storage_key"],))
            db.commit()
            return None
        db.execute("DELETE FROM blobs WHERE storage_key=?", (row["storage_key"],))
        db.commit()
        return str(row["blob_path"])

    def create_attachment(self, record: dict[str, Any]) -> None:
        columns = ",".join(record)
        marks = ",".join("?" for _ in record)
        self.connection().execute(f"INSERT INTO attachments ({columns}) VALUES ({marks})", tuple(record.values()))
        self.connection().commit()

    def get_attachment(self, attachment_id: str, include_deleted: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM attachments WHERE id=?"
        params: tuple[Any, ...] = (attachment_id,)
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        row = self.connection().execute(query, params).fetchone()
        return dict(row) if row else None

    def list_indexable_attachment_ids(self) -> list[str]:
        rows = self.connection().execute(
            "SELECT id FROM attachments WHERE status IN ('ready','needs_review') ORDER BY created_at,id"
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_library_versions(
        self,
        owner_id: str,
        knowledge_base_id: str,
        *,
        document_ids: list[str] | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM attachments WHERE owner_id=? AND knowledge_base_id=? "
            "AND source_scope='personal' AND scope='library' AND deleted_at IS NULL"
        )
        params: list[Any] = [owner_id, knowledge_base_id]
        if active_only:
            query += " AND active=1 AND status='ready'"
        if document_ids is not None:
            if not document_ids:
                return []
            query += " AND document_id IN (" + ",".join("?" for _ in document_ids) + ")"
            params.extend(document_ids)
        query += " ORDER BY created_at DESC,id"
        return [dict(row) for row in self.connection().execute(query, tuple(params)).fetchall()]

    def activate_library_version(self, attachment_id: str) -> list[str]:
        """Atomically switch a document to a READY version and return stale version ids."""
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT * FROM attachments WHERE id=? AND scope='library' "
            "AND source_scope='personal' AND deleted_at IS NULL",
            (attachment_id,),
        ).fetchone()
        if not current:
            db.rollback()
            raise KeyError("library_version_not_found")
        old_rows = db.execute(
            "SELECT id FROM attachments WHERE document_id=? AND id<>? AND active=1",
            (current["document_id"], attachment_id),
        ).fetchall()
        old_ids = [str(row["id"]) for row in old_rows]
        now = int(time.time())
        db.execute(
            "UPDATE attachments SET active=0,updated_at=? WHERE document_id=? AND id<>?",
            (now, current["document_id"], attachment_id),
        )
        db.execute(
            "UPDATE attachments SET active=1,status='ready',error_code='',updated_at=? WHERE id=?",
            (now, attachment_id),
        )
        db.commit()
        return old_ids

    def update_attachment(self, attachment_id: str, **values: Any) -> None:
        values["updated_at"] = int(time.time())
        assignments = ",".join(f"{key}=?" for key in values)
        self.connection().execute(
            f"UPDATE attachments SET {assignments} WHERE id=?",
            (*values.values(), attachment_id),
        )
        self.connection().commit()

    def transition_attachment(self, attachment_id: str, status: str, **values: Any) -> None:
        record = self.get_attachment(attachment_id, include_deleted=True)
        if not record:
            raise KeyError("attachment_not_found")
        current = str(record["status"])
        if status != current and status not in self.STATUS_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid_attachment_transition:{current}:{status}")
        self.update_attachment(attachment_id, status=status, **values)

    def transition_vision(self, attachment_id: str, status: str) -> None:
        record = self.get_attachment(attachment_id, include_deleted=True)
        if not record:
            raise KeyError("attachment_not_found")
        current = str(record["vision_status"])
        if status != current and status not in self.VISION_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid_vision_transition:{current}:{status}")
        self.update_attachment(attachment_id, vision_status=status)

    def enqueue(self, job_id: str, attachment_id: str, kind: str, payload: dict[str, Any] | None = None) -> None:
        now = int(time.time())
        self.connection().execute(
            "INSERT INTO jobs(id,attachment_id,kind,status,payload,created_at,updated_at) VALUES(?,?,?,'queued',?,?,?)",
            (job_id, attachment_id, kind, json.dumps(payload or {}), now, now),
        )
        self.connection().commit()

    def claim_job(self) -> dict[str, Any] | None:
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            db.commit()
            return None
        now = int(time.time())
        db.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now, row["id"]))
        db.commit()
        result = dict(row)
        result["payload"] = json.loads(result.get("payload") or "{}")
        return result

    def complete_job(self, job_id: str, *, error_code: str = "") -> None:
        status = "failed" if error_code else "completed"
        self.connection().execute(
            "UPDATE jobs SET status=?,error_code=?,updated_at=? WHERE id=?",
            (status, error_code, int(time.time()), job_id),
        )
        self.connection().commit()

    def requeue_job(self, job_id: str, error_code: str) -> None:
        self.connection().execute(
            "UPDATE jobs SET status='queued',error_code=?,updated_at=? WHERE id=?",
            (error_code, int(time.time()), job_id),
        )
        self.connection().commit()

    def has_active_job(self, attachment_id: str, kind: str) -> bool:
        row = self.connection().execute(
            "SELECT 1 FROM jobs WHERE attachment_id=? AND kind=? AND status IN ('queued','running') LIMIT 1",
            (attachment_id, kind),
        ).fetchone()
        return row is not None

    def replace_evidence(self, attachment_id: str, items: list[dict[str, Any]]) -> None:
        db = self.connection()
        now = int(time.time())
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM evidence WHERE attachment_id=?", (attachment_id,))
        db.execute("DELETE FROM evidence_fts WHERE attachment_id=?", (attachment_id,))
        for item in items:
            db.execute(
                "INSERT INTO evidence(id,attachment_id,source_type,original_content,current_content,locator,confidence,parser,version,confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,0,?,?)",
                (item["evidence_id"], attachment_id, item["source_type"], item["content"], item["content"], json.dumps(item.get("locator") or {}, ensure_ascii=False), item.get("confidence"), item["parser"], now, now),
            )
            db.execute(
                "INSERT INTO evidence_fts(evidence_id,attachment_id,content) VALUES(?,?,?)",
                (item["evidence_id"], attachment_id, item["content"]),
            )
        db.commit()

    def replace_derivatives(self, attachment_id: str, items: list[dict[str, Any]]) -> list[str]:
        db = self.connection()
        now = int(time.time())
        db.execute("BEGIN IMMEDIATE")
        old = [row["blob_path"] for row in db.execute(
            "SELECT blob_path FROM derivatives WHERE attachment_id=?", (attachment_id,)
        ).fetchall()]
        db.execute("DELETE FROM derivatives WHERE attachment_id=?", (attachment_id,))
        for item in items:
            db.execute(
                "INSERT INTO derivatives(id,attachment_id,kind,locator,mime_type,blob_path,key_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (item["id"], attachment_id, item["kind"], json.dumps(item.get("locator") or {}, ensure_ascii=False), item["mime_type"], item["blob_path"], item["key_id"], now),
            )
        db.commit()
        return old

    def list_derivatives(self, attachment_id: str) -> list[dict[str, Any]]:
        rows = self.connection().execute(
            "SELECT * FROM derivatives WHERE attachment_id=? ORDER BY kind,id", (attachment_id,)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["locator"] = json.loads(item["locator"] or "{}")
            result.append(item)
        return result

    def get_derivative(self, attachment_id: str, derivative_id: str) -> dict[str, Any] | None:
        row = self.connection().execute(
            "SELECT * FROM derivatives WHERE attachment_id=? AND id=?",
            (attachment_id, derivative_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["locator"] = json.loads(item["locator"] or "{}")
        return item

    def list_evidence(self, attachment_ids: list[str]) -> list[dict[str, Any]]:
        if not attachment_ids:
            return []
        marks = ",".join("?" for _ in attachment_ids)
        rows = self.connection().execute(
            f"SELECT * FROM evidence WHERE attachment_id IN ({marks}) ORDER BY attachment_id,created_at,id",
            tuple(attachment_ids),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence_id"] = item.pop("id")
            item["content"] = item.pop("current_content")
            item["locator"] = json.loads(item["locator"] or "{}")
            item["confirmed"] = bool(item["confirmed"])
            result.append(item)
        return result

    def add_evidence(self, attachment_id: str, item: dict[str, Any]) -> None:
        db = self.connection()
        now = int(time.time())
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO evidence(id,attachment_id,source_type,original_content,current_content,locator,confidence,parser,version,confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,0,?,?)",
            (item["evidence_id"], attachment_id, item["source_type"], item["content"], item["content"], json.dumps(item.get("locator") or {}, ensure_ascii=False), item.get("confidence"), item["parser"], now, now),
        )
        db.execute("INSERT INTO evidence_fts(evidence_id,attachment_id,content) VALUES(?,?,?)", (item["evidence_id"], attachment_id, item["content"]))
        db.commit()

    def revise_evidence(self, attachment_id: str, evidence_id: str, expected_version: int, content: str, reason: str, actor_id: str, revision_id: str) -> dict[str, Any] | None:
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM evidence WHERE id=? AND attachment_id=?",
            (evidence_id, attachment_id),
        ).fetchone()
        if not row or row["version"] != expected_version:
            db.rollback()
            return None
        now = int(time.time())
        next_version = expected_version + 1
        db.execute(
            "INSERT INTO evidence_revisions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (revision_id, evidence_id, row["attachment_id"], row["current_content"], content, reason, actor_id, expected_version, next_version, now),
        )
        db.execute("UPDATE evidence SET current_content=?,version=?,confirmed=1,updated_at=? WHERE id=?", (content, next_version, now, evidence_id))
        db.execute("UPDATE evidence_fts SET content=? WHERE evidence_id=?", (content, evidence_id))
        db.execute("UPDATE attachments SET evidence_version=evidence_version+1,updated_at=? WHERE id=?", (now, row["attachment_id"]))
        db.commit()
        return self.list_evidence([row["attachment_id"]])

    def list_revisions(self, attachment_id: str, evidence_id: str) -> list[dict[str, Any]]:
        rows = self.connection().execute(
            "SELECT * FROM evidence_revisions WHERE evidence_id=? AND attachment_id=? ORDER BY created_at,id",
            (evidence_id, attachment_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_evidence(self, attachment_ids: list[str], query: str, top_k: int) -> list[dict[str, Any]]:
        if not attachment_ids:
            return []
        terms = [term for term in query.replace('"', ' ').split() if term]
        if terms:
            expression = " OR ".join(f'"{term}"' for term in terms[:20])
            try:
                marks = ",".join("?" for _ in attachment_ids)
                rows = self.connection().execute(
                    "SELECT evidence_id,attachment_id,bm25(evidence_fts) AS rank "
                    f"FROM evidence_fts WHERE evidence_fts MATCH ? "
                    f"AND attachment_id IN ({marks}) ORDER BY rank LIMIT ?",
                    (expression, *attachment_ids, max(top_k * 10, 50)),
                ).fetchall()
                ranked = [
                    (row["evidence_id"], row["attachment_id"], -float(row["rank"]))
                    for row in rows
                ]
            except sqlite3.OperationalError:
                ranked = []
        else:
            ranked = []
        evidence = {item["evidence_id"]: item for item in self.list_evidence(attachment_ids)}
        marks = ",".join("?" for _ in attachment_ids)
        filenames = {
            row["id"]: row["filename"]
            for row in self.connection().execute(
                f"SELECT id,filename FROM attachments WHERE id IN ({marks})",
                tuple(attachment_ids),
            ).fetchall()
        }
        for item in evidence.values():
            item["filename"] = filenames.get(item["attachment_id"], item["attachment_id"])
        if not ranked:
            normalized = query.casefold().strip()
            tokens = [token for token in terms if token]
            if normalized:
                scored = []
                for item in evidence.values():
                    content = item["content"].casefold()
                    hits = sum(content.count(token.casefold()) for token in tokens)
                    if normalized in content:
                        hits += 3
                    if hits:
                        candidate = dict(item)
                        candidate["score"] = min(1.0, 0.25 + hits * 0.15)
                        scored.append(candidate)
                return sorted(scored, key=lambda value: (-value["score"], value["evidence_id"]))[:top_k]
            return list(evidence.values())[:top_k]
        result = []
        for evidence_id, _, score in ranked[:top_k]:
            if evidence_id in evidence:
                evidence[evidence_id]["score"] = min(1.0, max(0.0, score))
                result.append(evidence[evidence_id])
        return result

    def soft_delete(self, attachment_id: str, status: str = "deleted") -> None:
        now = int(time.time())
        self.transition_attachment(attachment_id, status, deleted_at=now)

    def purge(self, attachment_id: str) -> None:
        db = self.connection()
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM evidence_fts WHERE attachment_id=?", (attachment_id,))
        db.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
        db.commit()

    def expire(self) -> list[str]:
        now = int(time.time())
        rows = self.connection().execute(
            "SELECT id FROM attachments WHERE expires_at IS NOT NULL AND expires_at<=? AND status NOT IN ('expired','deleted')",
            (now,),
        ).fetchall()
        ids = [row["id"] for row in rows]
        for attachment_id in ids:
            self.transition_attachment(attachment_id, "expired", deleted_at=now)
        return ids
