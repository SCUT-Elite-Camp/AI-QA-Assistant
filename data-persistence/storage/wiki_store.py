"""Revisioned SQLite store for evidence-grounded Wiki navigation pages."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable


class WikiStore:
    """Persist draft revisions and atomically publish only fully supported pages."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wiki_build_runs (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  status TEXT NOT NULL, input_hash TEXT NOT NULL,
                  generator_model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                  created_at INTEGER NOT NULL, activated_at INTEGER,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision)
                );
                CREATE INDEX IF NOT EXISTS wiki_build_input
                  ON wiki_build_runs(source_scope,owner_id,knowledge_base_id,input_hash,status);
                CREATE UNIQUE INDEX IF NOT EXISTS wiki_one_published_run
                  ON wiki_build_runs(source_scope,owner_id,knowledge_base_id)
                  WHERE status='PUBLISHED';
                CREATE TABLE IF NOT EXISTS wiki_reviewed_releases (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  source_revision TEXT NOT NULL, review_sha256 TEXT NOT NULL,
                  reviewer TEXT NOT NULL, reviewed_on TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision)
                );
                CREATE TABLE IF NOT EXISTS wiki_build_documents (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  document_id TEXT NOT NULL, document_version_id TEXT NOT NULL,
                  content_sha256 TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,document_version_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_candidates (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  candidate_id TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,candidate_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_candidate_sources (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  source_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                  document_id TEXT NOT NULL, document_version_id TEXT NOT NULL,
                  section_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
                  support_quote TEXT NOT NULL, quote_start INTEGER NOT NULL,
                  quote_end INTEGER NOT NULL, evidence_sha256 TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,source_id,candidate_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_identities (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  identity_id TEXT NOT NULL, kind TEXT NOT NULL,
                  canonical_name TEXT NOT NULL, slug TEXT NOT NULL,
                  category TEXT, description TEXT NOT NULL,
                  candidate_ids TEXT NOT NULL, source_ids TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,identity_id),
                  UNIQUE(source_scope,owner_id,knowledge_base_id,revision,slug)
                );
                CREATE TABLE IF NOT EXISTS wiki_identity_aliases (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  identity_id TEXT NOT NULL, alias TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,identity_id,alias)
                );
                CREATE TABLE IF NOT EXISTS wiki_folders (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  folder_id TEXT NOT NULL, title TEXT NOT NULL,
                  parent_id TEXT, depth INTEGER NOT NULL, manual INTEGER NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,folder_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_pages (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, page_id TEXT NOT NULL,
                  page_type TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
                  identity_id TEXT, PRIMARY KEY(source_scope,owner_id,knowledge_base_id,page_id),
                  UNIQUE(source_scope,owner_id,knowledge_base_id,slug)
                );
                CREATE TABLE IF NOT EXISTS wiki_page_revisions (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, page_type TEXT NOT NULL, slug TEXT NOT NULL,
                  title TEXT NOT NULL, identity_id TEXT,
                  status TEXT NOT NULL, summary TEXT NOT NULL,
                  folder_id TEXT, document_version_ids TEXT NOT NULL,
                  input_hash TEXT NOT NULL, generator_model TEXT NOT NULL,
                  prompt_version TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_page_claims (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, claim_id TEXT NOT NULL, section_heading TEXT NOT NULL,
                  claim_text TEXT NOT NULL, verdict TEXT, reason_code TEXT, reason TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,claim_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_page_sources (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, claim_id TEXT NOT NULL, source_id TEXT NOT NULL,
                  document_id TEXT NOT NULL, document_version_id TEXT NOT NULL,
                  section_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
                  support_quote TEXT NOT NULL, quote_start INTEGER NOT NULL,
                  quote_end INTEGER NOT NULL, evidence_sha256 TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,claim_id,source_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_page_links (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, target_page_id TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,target_page_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_page_issues (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  issue_index INTEGER NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL,
                  target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,issue_index)
                );
                CREATE TABLE IF NOT EXISTS wiki_claim_audits (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, audit_round INTEGER NOT NULL,
                  claim_id TEXT NOT NULL, claim_text TEXT NOT NULL,
                  source_ids TEXT NOT NULL, verdict TEXT NOT NULL,
                  reason_code TEXT NOT NULL, reason TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,audit_round,claim_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_claim_repairs (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, repair_round INTEGER NOT NULL,
                  original_claim_id TEXT NOT NULL, original_text TEXT NOT NULL,
                  action TEXT NOT NULL, repaired_claim_id TEXT NOT NULL,
                  repaired_text TEXT NOT NULL, source_ids TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,repair_round,original_claim_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts USING fts5(
                  page_id UNINDEXED, source_scope UNINDEXED, owner_id UNINDEXED,
                  knowledge_base_id UNINDEXED, revision UNINDEXED, search_text
                );
                CREATE TABLE IF NOT EXISTS wiki_page_vectors (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, revision TEXT NOT NULL,
                  page_id TEXT NOT NULL, model_id TEXT NOT NULL,
                  embedding BLOB NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,page_id,model_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_llm_completion_cache (
                  cache_key TEXT PRIMARY KEY, model TEXT NOT NULL,
                  schema_name TEXT NOT NULL, response TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wiki_jobs (
                  job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, document_id TEXT NOT NULL,
                  document_version_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                  stage TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL,
                  max_attempts INTEGER NOT NULL, next_retry_at INTEGER NOT NULL,
                  lease_owner TEXT NOT NULL, lease_expires_at INTEGER NOT NULL,
                  payload TEXT NOT NULL, last_error TEXT NOT NULL,
                  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS wiki_jobs_ready
                  ON wiki_jobs(status,next_retry_at,lease_expires_at,created_at);
                CREATE TABLE IF NOT EXISTS wiki_pending_ops (
                  op_id TEXT PRIMARY KEY, source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, document_id TEXT NOT NULL,
                  document_version_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                  op_type TEXT NOT NULL DEFAULT 'UPSERT',
                  coalesced_count INTEGER NOT NULL, requested_at INTEGER NOT NULL,
                  UNIQUE(source_scope,owner_id,knowledge_base_id,document_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_source_tombstones (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, document_id TEXT NOT NULL,
                  document_version_id TEXT NOT NULL, deleted_at INTEGER NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,document_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_dead_letters (
                  dead_letter_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, stage TEXT NOT NULL,
                  payload TEXT NOT NULL, error TEXT NOT NULL, attempts INTEGER NOT NULL,
                  created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wiki_identity_claims (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, slug TEXT NOT NULL,
                  worker_id TEXT NOT NULL, lease_expires_at INTEGER NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,slug)
                );
                CREATE TABLE IF NOT EXISTS wiki_finalize_requests (
                  source_scope TEXT NOT NULL, owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL, status TEXT NOT NULL,
                  generation INTEGER NOT NULL, requested_at INTEGER NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id)
                );
            """)
            for column, declaration in (
                ("page_type", "TEXT NOT NULL DEFAULT ''"),
                ("slug", "TEXT NOT NULL DEFAULT ''"),
                ("title", "TEXT NOT NULL DEFAULT ''"),
                ("identity_id", "TEXT"),
            ):
                if column not in {
                    row["name"] for row in db.execute("PRAGMA table_info(wiki_page_revisions)")
                }:
                    db.execute(f"ALTER TABLE wiki_page_revisions ADD COLUMN {column} {declaration}")
            if "op_type" not in {row["name"] for row in db.execute("PRAGMA table_info(wiki_pending_ops)")}:
                db.execute("ALTER TABLE wiki_pending_ops ADD COLUMN op_type TEXT NOT NULL DEFAULT 'UPSERT'")

    def get_completion(self, cache_key: str) -> dict[str, Any] | None:
        if len(cache_key) != 64:
            raise ValueError("Wiki completion cache key must be a SHA-256 digest")
        with self.connection() as db:
            row = db.execute(
                "SELECT response FROM wiki_llm_completion_cache WHERE cache_key=?", (cache_key,),
            ).fetchone()
        return json.loads(row["response"]) if row else None

    def put_completion(
        self, cache_key: str, *, model: str, schema_name: str, response: dict[str, Any],
    ) -> None:
        if len(cache_key) != 64 or not model.strip() or not schema_name.strip():
            raise ValueError("Wiki completion cache metadata is invalid")
        with self.connection() as db:
            db.execute(
                "INSERT INTO wiki_llm_completion_cache(cache_key,model,schema_name,response,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(cache_key) DO NOTHING",
                (cache_key, model, schema_name, _json(response), int(time.time())),
            )

    def enqueue_wiki_job(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        document_id: str, document_version_id: str, content_sha256: str,
        payload: dict[str, Any] | None = None, max_attempts: int = 5,
    ) -> str:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        if not document_id.strip() or not document_version_id.strip() or len(content_sha256) != 64:
            raise ValueError("Wiki job document identity is invalid")
        if max_attempts < 1:
            raise ValueError("Wiki job max_attempts must be positive")
        material = "\n".join([scope, owner, kb, document_id, document_version_id, content_sha256])
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        job_id = f"wj_{digest[:24]}"
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                "INSERT INTO wiki_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(idempotency_key) DO NOTHING",
                (job_id, digest, scope, owner, kb, document_id, document_version_id,
                 content_sha256, "EXTRACT", "PENDING", 0, max_attempts, now, "", 0,
                 _json(payload or {}), "", now, now),
            )
        return job_id

    def lease_wiki_job(
        self, *, worker_id: str, lease_seconds: int = 60, now: int | None = None,
        source_scope: str | None = None, owner_id: str = "", knowledge_base_id: str = "",
    ) -> dict[str, Any] | None:
        if not worker_id.strip() or lease_seconds < 1:
            raise ValueError("Wiki job lease metadata is invalid")
        if bool(source_scope) != bool(knowledge_base_id):
            raise ValueError("Wiki lease scope filter is incomplete")
        filtered = self._context(source_scope, owner_id, knowledge_base_id) if source_scope else None
        scope_sql = (
            " AND wiki_jobs.source_scope=? AND wiki_jobs.owner_id=? AND "
            "wiki_jobs.knowledge_base_id=?" if filtered else ""
        )
        timestamp = int(time.time()) if now is None else int(now)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            exhausted = db.execute(
                "SELECT * FROM wiki_jobs WHERE status='RUNNING' AND lease_expires_at<=? "
                "AND attempt>=max_attempts" + scope_sql, (timestamp, *(filtered or ())),
            ).fetchall()
            for expired in exhausted:
                db.execute(
                    "UPDATE wiki_jobs SET status='DEAD',lease_owner='',lease_expires_at=0,"
                    "last_error='lease expired after final attempt',updated_at=? WHERE job_id=?",
                    (timestamp, expired["job_id"]),
                )
                dead_id = f"wd_{hashlib.sha256((expired['job_id'] + str(expired['attempt'])).encode()).hexdigest()[:24]}"
                db.execute(
                    "INSERT OR IGNORE INTO wiki_dead_letters VALUES(?,?,?,?,?,?,?)",
                    (dead_id, expired["job_id"], expired["stage"], expired["payload"],
                     "lease expired after final attempt", expired["attempt"], timestamp),
                )
            row = db.execute(
                "SELECT * FROM wiki_jobs WHERE "
                "((status IN ('PENDING','RETRY') AND next_retry_at<=?) "
                "OR (status='RUNNING' AND lease_expires_at<=?)) AND attempt<max_attempts "
                + scope_sql +
                " AND NOT EXISTS (SELECT 1 FROM wiki_jobs older WHERE older.job_id!=wiki_jobs.job_id "
                "AND older.source_scope=wiki_jobs.source_scope AND older.owner_id=wiki_jobs.owner_id "
                "AND older.knowledge_base_id=wiki_jobs.knowledge_base_id "
                "AND older.status IN ('PENDING','RETRY','RUNNING') "
                "AND older.rowid<wiki_jobs.rowid) "
                "ORDER BY wiki_jobs.rowid LIMIT 1", (timestamp, timestamp, *(filtered or ())),
            ).fetchone()
            if row is None:
                return None
            lease_expires = timestamp + lease_seconds
            db.execute(
                "UPDATE wiki_jobs SET status='RUNNING',attempt=attempt+1,lease_owner=?,"
                "lease_expires_at=?,updated_at=? WHERE job_id=?",
                (worker_id, lease_expires, timestamp, row["job_id"]),
            )
            value = dict(row)
            value.update({"status": "RUNNING", "attempt": row["attempt"] + 1,
                          "lease_owner": worker_id, "lease_expires_at": lease_expires,
                          "payload": json.loads(row["payload"])})
            return value

    def advance_wiki_job(
        self, job_id: str, *, worker_id: str, next_stage: Any | None,
        payload: dict[str, Any] | None = None, attempt: int | None = None,
    ) -> None:
        stage = str(next_stage.value if hasattr(next_stage, "value") else next_stage or "")
        valid = {"EXTRACT", "CITE", "PROMOTE", "RESOLVE", "COMPILE", "VERIFY", "FINALIZE", "PUBLISH"}
        if stage and stage not in valid:
            raise ValueError("unknown Wiki job stage")
        now = int(time.time())
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE wiki_jobs SET stage=CASE WHEN ?='' THEN stage ELSE ? END,status=?,attempt=0,"
                "lease_owner='',lease_expires_at=0,next_retry_at=?,updated_at=?,"
                "payload=CASE WHEN ? IS NULL THEN payload ELSE ? END "
                "WHERE job_id=? AND status='RUNNING' AND lease_owner=? "
                "AND (? IS NULL OR attempt=?) AND lease_expires_at>?",
                (stage, stage, "PENDING" if stage else "COMPLETE", now, now,
                 None if payload is None else 1, _json(payload) if payload is not None else "",
                 job_id, worker_id, attempt, attempt, now),
            )
            if cursor.rowcount != 1:
                raise ValueError("Wiki job is not leased by this worker")

    def fail_wiki_job(
        self, job_id: str, *, worker_id: str, error: str, retry_at: int,
    ) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM wiki_jobs WHERE job_id=? AND status='RUNNING' AND lease_owner=?",
                (job_id, worker_id),
            ).fetchone()
            if row is None:
                raise ValueError("Wiki job is not leased by this worker")
            dead = row["attempt"] >= row["max_attempts"]
            status = "DEAD" if dead else "RETRY"
            db.execute(
                "UPDATE wiki_jobs SET status=?,next_retry_at=?,lease_owner='',lease_expires_at=0,"
                "last_error=?,updated_at=? WHERE job_id=?",
                (status, int(retry_at), error[:2000], now, job_id),
            )
            if dead:
                dead_id = f"wd_{hashlib.sha256((job_id + str(row['attempt'])).encode()).hexdigest()[:24]}"
                db.execute(
                    "INSERT OR IGNORE INTO wiki_dead_letters VALUES(?,?,?,?,?,?,?)",
                    (dead_id, job_id, row["stage"], row["payload"], error[:2000], row["attempt"], now),
                )

    def renew_wiki_job_lease(
        self, job_id: str, *, worker_id: str, attempt: int,
        lease_seconds: int = 600,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("Wiki lease_seconds must be positive")
        now = int(time.time())
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE wiki_jobs SET lease_expires_at=?,updated_at=? WHERE job_id=? "
                "AND status='RUNNING' AND lease_owner=? AND attempt=? AND lease_expires_at>?",
                (now + lease_seconds, now, job_id, worker_id, attempt, now),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _require_job_lease(
        db: sqlite3.Connection, guard: tuple[str, str, int] | None,
    ) -> None:
        if guard is None:
            return
        row = db.execute(
            "SELECT 1 FROM wiki_jobs WHERE job_id=? AND lease_owner=? AND attempt=? "
            "AND status='RUNNING' AND lease_expires_at>?", (*guard, int(time.time())),
        ).fetchone()
        if row is None:
            raise ValueError("Wiki job lease was lost before writing")

    def upsert_pending_wiki_op(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        document_id: str, document_version_id: str, content_sha256: str,
        operation: str = "UPSERT",
    ) -> str:
        if (operation not in {"UPSERT", "DELETE"} or not document_id.strip()
                or not document_version_id.strip()
                or len(content_sha256) != 64
                or any(char not in "0123456789abcdef" for char in content_sha256)):
            raise ValueError("invalid Wiki pending operation")
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        digest = hashlib.sha256("\n".join([scope, owner, kb, document_id]).encode()).hexdigest()
        op_id = f"wo_{digest[:24]}"
        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if operation == "DELETE":
                db.execute(
                    "INSERT INTO wiki_source_tombstones VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(source_scope,owner_id,knowledge_base_id,document_id) DO UPDATE SET "
                    "document_version_id=excluded.document_version_id,deleted_at=excluded.deleted_at",
                    (scope, owner, kb, document_id, document_version_id, now),
                )
            db.execute(
                "INSERT INTO wiki_pending_ops VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source_scope,owner_id,knowledge_base_id,document_id) DO UPDATE SET "
                "document_version_id=excluded.document_version_id,content_sha256=excluded.content_sha256,"
                "op_type=excluded.op_type,"
                "coalesced_count=wiki_pending_ops.coalesced_count+1,requested_at=excluded.requested_at",
                (op_id, scope, owner, kb, document_id, document_version_id,
                 content_sha256, operation, 1, now),
            )
        return op_id

    def reactivate_wiki_source(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Clear a tombstone only after the authoritative active projection is read."""
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            db.execute(
                "DELETE FROM wiki_source_tombstones WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND document_id=?",
                (scope, owner, kb, document_id),
            )

    def tombstoned_document_ids(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> set[str]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            return {row[0] for row in db.execute(
                "SELECT document_id FROM wiki_source_tombstones WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=?", (scope, owner, kb),
            )}

    @staticmethod
    def _reject_tombstoned_documents(
        db: sqlite3.Connection, key: tuple[str, str, str, str],
        documents: Iterable[Any],
    ) -> None:
        for document in documents:
            row = db.execute(
                "SELECT 1 FROM wiki_source_tombstones WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND document_id=?",
                (*key[:3], document["document_id"]),
            ).fetchone()
            if row:
                raise ValueError("Wiki source document was deleted during build")

    def lifecycle_scopes(self) -> list[tuple[str, str, str]]:
        """Scopes with persisted enterprise Wiki work, including deleted-source scopes."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT source_scope,owner_id,knowledge_base_id FROM wiki_build_runs "
                "UNION SELECT source_scope,owner_id,knowledge_base_id FROM wiki_pending_ops "
                "UNION SELECT source_scope,owner_id,knowledge_base_id FROM wiki_jobs "
                "ORDER BY source_scope,owner_id,knowledge_base_id"
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def lifecycle_observed_documents(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> tuple[bool, dict[str, tuple[str, str]]]:
        """Last built source set overlaid by unscheduled changes.

        Reconciliation waits while a scope job is active. Once it completes,
        its revision becomes the comparison baseline; if it dies, the old
        baseline causes the missed change to be queued again.
        """
        key = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            active = db.execute(
                "SELECT 1 FROM wiki_jobs WHERE source_scope=? AND owner_id=? AND "
                "knowledge_base_id=? AND status IN ('PENDING','RUNNING','RETRY') LIMIT 1",
                key,
            ).fetchone() is not None
            latest = db.execute(
                "SELECT revision FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND status IN ('DRAFT','PUBLISHED') "
                "ORDER BY created_at DESC,rowid DESC LIMIT 1", key,
            ).fetchone()
            observed: dict[str, tuple[str, str]] = {}
            if latest is not None:
                for row in db.execute(
                    "SELECT document_id,document_version_id,content_sha256 FROM "
                    "wiki_build_documents WHERE source_scope=? AND owner_id=? AND "
                    "knowledge_base_id=? AND revision=?",
                    (*key, latest["revision"]),
                ):
                    observed[row["document_id"]] = (row["document_version_id"], row["content_sha256"])
            for row in db.execute(
                "SELECT document_id,document_version_id,content_sha256,op_type FROM "
                "wiki_pending_ops WHERE source_scope=? AND owner_id=? AND knowledge_base_id=?",
                key,
            ):
                if row["op_type"] == "DELETE":
                    observed.pop(row["document_id"], None)
                else:
                    observed[row["document_id"]] = (row["document_version_id"], row["content_sha256"])
        return active, observed

    def schedule_pending_wiki_jobs(
        self, *, debounce_seconds: int = 0, now: int | None = None,
        intent: str = "PREVIEW",
    ) -> list[str]:
        """Atomically turn each ready scope's coalesced operations into one build job."""
        if debounce_seconds < 0 or intent not in {"PREVIEW", "PUBLISH"}:
            raise ValueError("Wiki scheduling configuration is invalid")
        timestamp = int(time.time()) if now is None else int(now)
        scheduled: list[str] = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            scopes = db.execute(
                "SELECT source_scope,owner_id,knowledge_base_id,MAX(requested_at) AS latest "
                "FROM wiki_pending_ops GROUP BY source_scope,owner_id,knowledge_base_id "
                "HAVING MAX(requested_at)<=?", (timestamp - debounce_seconds,),
            ).fetchall()
            for scope in scopes:
                key = (scope["source_scope"], scope["owner_id"], scope["knowledge_base_id"])
                changes = [dict(row) for row in db.execute(
                    "SELECT document_id,document_version_id,content_sha256,op_type "
                    "FROM wiki_pending_ops WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? "
                    "ORDER BY document_id", key,
                )]
                digest = hashlib.sha256(_json([*key, intent, changes]).encode("utf-8")).hexdigest()
                job_id = f"wj_{digest[:24]}"
                current = db.execute(
                    "SELECT generation FROM wiki_finalize_requests WHERE source_scope=? "
                    "AND owner_id=? AND knowledge_base_id=?", key,
                ).fetchone()
                generation = (current["generation"] if current else 0) + 1
                inserted = db.execute(
                    "INSERT INTO wiki_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(idempotency_key) DO NOTHING",
                    (job_id, digest, *key, "scope-batch", f"batch-{digest[:24]}", digest,
                     "EXTRACT", "PENDING", 0, 5, timestamp, "", 0,
                     _json({"changes": changes, "finalize_generation": generation,
                            "intent": intent}),
                     "", timestamp, timestamp),
                )
                if inserted.rowcount == 0:
                    existing = db.execute(
                        "SELECT status FROM wiki_jobs WHERE idempotency_key=?", (digest,),
                    ).fetchone()
                    if existing["status"] == "DEAD":
                        db.execute(
                            "UPDATE wiki_jobs SET stage='EXTRACT',status='PENDING',attempt=0,"
                            "next_retry_at=?,lease_owner='',lease_expires_at=0,last_error='',"
                            "updated_at=?,payload=? WHERE idempotency_key=?",
                            (timestamp, timestamp,
                             _json({"changes": changes, "finalize_generation": generation,
                                    "intent": intent}), digest),
                        )
                    else:
                        db.execute(
                            "DELETE FROM wiki_pending_ops WHERE source_scope=? AND owner_id=? "
                            "AND knowledge_base_id=?", key,
                        )
                        continue
                db.execute(
                    "DELETE FROM wiki_pending_ops WHERE source_scope=? AND owner_id=? AND knowledge_base_id=?",
                    key,
                )
                db.execute(
                    "INSERT INTO wiki_finalize_requests VALUES(?,?,?,'PENDING',1,?) "
                    "ON CONFLICT(source_scope,owner_id,knowledge_base_id) DO UPDATE SET "
                    "status='PENDING',generation=wiki_finalize_requests.generation+1,"
                    "requested_at=excluded.requested_at", (*key, timestamp),
                )
                scheduled.append(job_id)
        return scheduled

    def complete_wiki_finalize(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        generation: int,
    ) -> bool:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE wiki_finalize_requests SET status='COMPLETE' WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=? AND generation=? "
                "AND NOT EXISTS (SELECT 1 FROM wiki_pending_ops WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=?)",
                (scope, owner, kb, generation, scope, owner, kb),
            )
            return cursor.rowcount == 1

    def request_wiki_finalize(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                "INSERT INTO wiki_finalize_requests VALUES(?,?,?,'PENDING',1,?) "
                "ON CONFLICT(source_scope,owner_id,knowledge_base_id) DO UPDATE SET "
                "status='PENDING',generation=wiki_finalize_requests.generation+1,"
                "requested_at=excluded.requested_at",
                (scope, owner, kb, now),
            )

    def claim_wiki_slug(
        self, slug: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, worker_id: str, lease_seconds: int = 60,
        now: int | None = None,
    ) -> bool:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        if not slug.strip() or not worker_id.strip() or lease_seconds < 1:
            raise ValueError("Wiki slug lease metadata is invalid")
        timestamp = int(time.time()) if now is None else int(now)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT worker_id,lease_expires_at FROM wiki_identity_claims WHERE "
                "source_scope=? AND owner_id=? AND knowledge_base_id=? AND slug=?",
                (scope, owner, kb, slug),
            ).fetchone()
            if row and row["worker_id"] != worker_id and row["lease_expires_at"] > timestamp:
                return False
            db.execute(
                "INSERT INTO wiki_identity_claims VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(source_scope,owner_id,knowledge_base_id,slug) DO UPDATE SET "
                "worker_id=excluded.worker_id,lease_expires_at=excluded.lease_expires_at",
                (scope, owner, kb, slug, worker_id, timestamp + lease_seconds),
            )
            return True

    def release_wiki_slug(
        self, slug: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, worker_id: str,
    ) -> bool:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            cursor = db.execute(
                "DELETE FROM wiki_identity_claims WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND slug=? AND worker_id=?",
                (scope, owner, kb, slug, worker_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _context(source_scope: str, owner_id: str, knowledge_base_id: str) -> tuple[str, str, str]:
        scope = source_scope.casefold().strip()
        owner = owner_id.strip()
        kb = knowledge_base_id.strip()
        if scope not in {"enterprise", "personal"}:
            raise ValueError("source_scope must be enterprise or personal")
        if not kb:
            raise ValueError("knowledge_base_id is required")
        if scope == "personal" and not owner:
            raise ValueError("personal Wiki access requires owner_id")
        return scope, owner if scope == "personal" else "", kb

    def reusable_revision(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str, input_hash: str,
    ) -> str | None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            row = db.execute(
                "SELECT revision FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND input_hash=? AND status='PUBLISHED' "
                "ORDER BY activated_at DESC LIMIT 1",
                (scope, owner, kb, input_hash),
            ).fetchone()
        return str(row["revision"]) if row else None

    def load_published_candidates(
        self, document_version_id: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str,
    ) -> list[dict[str, Any]] | None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return None
            if db.execute(
                "SELECT 1 FROM wiki_reviewed_releases WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", (scope, owner, kb, revision),
            ).fetchone():
                return None
            processed = db.execute(
                "SELECT 1 FROM wiki_build_documents WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND document_version_id=?",
                (scope, owner, kb, revision, document_version_id),
            ).fetchone()
            if not processed:
                return None
            rows = db.execute(
                "SELECT DISTINCT c.payload FROM wiki_candidates c JOIN wiki_candidate_sources s "
                "ON c.source_scope=s.source_scope AND c.owner_id=s.owner_id AND c.knowledge_base_id=s.knowledge_base_id "
                "AND c.revision=s.revision AND c.candidate_id=s.candidate_id WHERE c.source_scope=? AND c.owner_id=? "
                "AND c.knowledge_base_id=? AND c.revision=? AND s.document_version_id=?",
                (scope, owner, kb, revision, document_version_id),
            ).fetchall()
            return [json.loads(row["payload"]) for row in rows]

    def load_published_identities(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> list[dict[str, Any]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return []
            rows = db.execute(
                "SELECT * FROM wiki_identities WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? ORDER BY identity_id",
                (scope, owner, kb, revision),
            ).fetchall()
            result = []
            for row in rows:
                aliases = db.execute(
                    "SELECT alias FROM wiki_identity_aliases WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=? AND identity_id=? ORDER BY alias",
                    (scope, owner, kb, revision, row["identity_id"]),
                ).fetchall()
                result.append({
                    "id": row["identity_id"],
                    "scope": {"source_scope": scope, "owner_id": owner, "knowledge_base_id": kb},
                    "kind": row["kind"], "canonical_name": row["canonical_name"], "slug": row["slug"],
                    "category": row["category"], "aliases": [item["alias"] for item in aliases],
                    "candidate_ids": json.loads(row["candidate_ids"]),
                    "source_ids": json.loads(row["source_ids"]), "description": row["description"],
                })
            return result

    def load_published_taxonomy(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return [], []
            folders = [{
                "id": row["folder_id"],
                "scope": {"source_scope": scope, "owner_id": owner, "knowledge_base_id": kb},
                "title": row["title"], "parent_id": row["parent_id"], "depth": row["depth"],
                "manual": bool(row["manual"]),
            } for row in db.execute(
                "SELECT * FROM wiki_folders WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? ORDER BY depth,title",
                (scope, owner, kb, revision),
            ).fetchall()]
            placements = [{
                "identity_id": row["identity_id"], "folder_id": row["folder_id"], "manual": False,
            } for row in db.execute(
                "SELECT r.identity_id,r.folder_id FROM wiki_page_revisions r "
                "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? "
                "AND r.revision=? AND r.identity_id IS NOT NULL AND r.folder_id IS NOT NULL",
                (scope, owner, kb, revision),
            ).fetchall()]
            return folders, placements

    def load_published_page_cache(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> dict[str, dict[str, Any]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return {}
            rows = db.execute(
                "SELECT input_hash,payload FROM wiki_page_revisions WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", (scope, owner, kb, revision),
            ).fetchall()
            return {row["input_hash"]: json.loads(row["payload"]) for row in rows}

    def load_published_page_audit_cache(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return {}
            page_hashes = {
                row["page_id"]: row["input_hash"] for row in db.execute(
                    "SELECT page_id,input_hash FROM wiki_page_revisions WHERE source_scope=? "
                    "AND owner_id=? AND knowledge_base_id=? AND revision=?",
                    (scope, owner, kb, revision),
                ).fetchall()
            }
            result = {value: {"audits": [], "repairs": []} for value in page_hashes.values()}
            for row in db.execute(
                "SELECT * FROM wiki_claim_audits WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? ORDER BY page_id,audit_round,claim_id",
                (scope, owner, kb, revision),
            ).fetchall():
                result[page_hashes[row["page_id"]]]["audits"].append({
                    "page_id": row["page_id"], "audit_round": row["audit_round"],
                    "claim_id": row["claim_id"], "claim_text": row["claim_text"],
                    "source_ids": json.loads(row["source_ids"]), "verdict": row["verdict"],
                    "reason_code": row["reason_code"], "reason": row["reason"],
                })
            for row in db.execute(
                "SELECT * FROM wiki_claim_repairs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? ORDER BY page_id,repair_round,original_claim_id",
                (scope, owner, kb, revision),
            ).fetchall():
                result[page_hashes[row["page_id"]]]["repairs"].append({
                    "page_id": row["page_id"], "repair_round": row["repair_round"],
                    "original_claim_id": row["original_claim_id"],
                    "original_text": row["original_text"], "action": row["action"],
                    "repaired_claim_id": row["repaired_claim_id"],
                    "repaired_text": row["repaired_text"],
                    "source_ids": json.loads(row["source_ids"]), "reason": row["reason"],
                })
            return result

    def save_artifact(
        self, artifact: Any, source_catalog: dict[str, Any], *,
        lease_guard: tuple[str, str, int] | None = None,
    ) -> None:
        payload = artifact.model_dump(mode="json") if hasattr(artifact, "model_dump") else dict(artifact)
        scope_value = payload["scope"]
        scope, owner, kb = self._context(
            scope_value["source_scope"], scope_value.get("owner_id", ""), scope_value["knowledge_base_id"],
        )
        revision = str(payload["revision"]).strip()
        if not revision or not str(payload["input_hash"]).strip():
            raise ValueError("Wiki artifact revision and input hash are required")
        candidates = payload.get("candidates") or []
        identities = payload.get("identities") or []
        folders = payload.get("folders") or []
        pages = payload.get("pages") or []
        if len({item["id"] for item in pages}) != len(pages):
            raise ValueError("Wiki artifact page IDs must be unique")
        page_ids = {item["id"] for item in pages}
        if any(set(item.get("links") or []) - page_ids for item in pages):
            raise ValueError("Wiki artifact contains a dead page link")
        normalized_sources = {
            key: value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
            for key, value in source_catalog.items()
        }
        for page in pages:
            for section in page.get("sections") or []:
                for claim in section.get("claims") or []:
                    if not set(claim.get("source_ids") or []) <= set(normalized_sources):
                        raise ValueError("Wiki artifact claim references an unknown source")

        now = int(time.time())
        key = (scope, owner, kb, revision)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_job_lease(db, lease_guard)
            self._reject_tombstoned_documents(db, key, payload.get("documents") or [])
            published = db.execute(
                "SELECT 1 FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND status='PUBLISHED'", key,
            ).fetchone()
            if published:
                raise ValueError("published Wiki revision is immutable")
            self._delete_revision(db, key)
            db.execute(
                "INSERT INTO wiki_build_runs VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (*key, "DRAFT", payload["input_hash"], payload["generator_model"], payload["prompt_version"], now),
            )
            for document in payload.get("documents") or []:
                db.execute(
                    "INSERT INTO wiki_build_documents VALUES(?,?,?,?,?,?,?)",
                    (*key, document["document_id"], document["document_version_id"], document["content_sha256"]),
                )
            candidate_by_id = {item["id"]: item for item in candidates}
            for candidate in candidates:
                db.execute(
                    "INSERT INTO wiki_candidates VALUES(?,?,?,?,?,?)",
                    (*key, candidate["id"], _json(candidate)),
                )
                for source in candidate.get("sources") or []:
                    source_id = _source_id(source)
                    db.execute(
                        "INSERT INTO wiki_candidate_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*key, source_id, candidate["id"], source["document_id"], source["document_version_id"],
                         source.get("section_id", ""), source["evidence_id"], source["support_quote"],
                         source["quote_start"], source["quote_end"], source["evidence_sha256"]),
                    )
            for identity in identities:
                if not set(identity["candidate_ids"]) <= set(candidate_by_id):
                    raise ValueError("Wiki identity references unknown candidates")
                db.execute(
                    "INSERT INTO wiki_identities VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*key, identity["id"], identity["kind"], identity["canonical_name"], identity["slug"],
                     identity.get("category"), identity.get("description", ""),
                     _json(identity["candidate_ids"]), _json(identity["source_ids"])),
                )
                for alias in identity.get("aliases") or []:
                    db.execute("INSERT INTO wiki_identity_aliases VALUES(?,?,?,?,?,?)", (*key, identity["id"], alias))
            for folder in folders:
                db.execute(
                    "INSERT INTO wiki_folders VALUES(?,?,?,?,?,?,?,?,?)",
                    (*key, folder["id"], folder["title"], folder.get("parent_id"), folder["depth"], int(folder.get("manual", False))),
                )
            for page in pages:
                db.execute(
                    "INSERT INTO wiki_pages VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(source_scope,owner_id,knowledge_base_id,page_id) DO NOTHING",
                    (scope, owner, kb, page["id"], page["page_type"], page["slug"], page["title"], page.get("identity_id")),
                )
                db.execute(
                    "INSERT INTO wiki_page_revisions("
                    "source_scope,owner_id,knowledge_base_id,revision,page_id,page_type,slug,title,identity_id,"
                    "status,summary,folder_id,document_version_ids,input_hash,generator_model,prompt_version,payload"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*key, page["id"], page["page_type"], page["slug"], page["title"], page.get("identity_id"),
                     page["status"], page.get("summary", ""), page.get("folder_id"),
                     _json(page.get("document_version_ids") or []), page["input_hash"],
                     page.get("generator_model", ""), page.get("prompt_version", ""), _json(page)),
                )
                for section in page.get("sections") or []:
                    for claim in section.get("claims") or []:
                        db.execute(
                            "INSERT INTO wiki_page_claims VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (*key, page["id"], claim["id"], section["heading"], claim["text"],
                             claim.get("verdict"), claim.get("reason_code"), claim.get("reason", "")),
                        )
                        for source_id in claim["source_ids"]:
                            source = normalized_sources[source_id]
                            db.execute(
                                "INSERT INTO wiki_page_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (*key, page["id"], claim["id"], source_id, source["document_id"],
                                 source["document_version_id"], source.get("section_id", ""), source["evidence_id"],
                                 source["support_quote"], source["quote_start"], source["quote_end"],
                                 source["evidence_sha256"]),
                            )
                for target in page.get("links") or []:
                    db.execute("INSERT INTO wiki_page_links VALUES(?,?,?,?,?,?)", (*key, page["id"], target))
            for index, issue in enumerate(payload.get("issues") or []):
                db.execute(
                    "INSERT INTO wiki_page_issues VALUES(?,?,?,?,?,?,?,?,?)",
                    (*key, index, issue["code"], issue["message"], issue["target_kind"], issue["target_id"]),
                )
            for audit in payload.get("claim_audits") or []:
                db.execute(
                    "INSERT INTO wiki_claim_audits VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*key, audit["page_id"], audit["audit_round"], audit["claim_id"],
                     audit["claim_text"], _json(audit["source_ids"]), audit["verdict"],
                     audit["reason_code"], audit.get("reason", "")),
                )
            for repair in payload.get("claim_repairs") or []:
                db.execute(
                    "INSERT INTO wiki_claim_repairs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*key, repair["page_id"], repair["repair_round"], repair["original_claim_id"],
                     repair["original_text"], repair["action"], repair.get("repaired_claim_id", ""),
                     repair.get("repaired_text", ""), _json(repair.get("source_ids") or []),
                     repair.get("reason", "")),
                )

    @staticmethod
    def _delete_revision(db: sqlite3.Connection, key: tuple[str, str, str, str]) -> None:
        for table in (
            "wiki_reviewed_releases", "wiki_page_vectors", "wiki_pages_fts", "wiki_page_issues", "wiki_claim_repairs", "wiki_claim_audits",
            "wiki_page_links", "wiki_page_sources",
            "wiki_page_claims", "wiki_page_revisions", "wiki_folders", "wiki_identity_aliases",
            "wiki_identities", "wiki_candidate_sources", "wiki_candidates", "wiki_build_runs",
            "wiki_build_documents",
        ):
            db.execute(
                f"DELETE FROM {table} WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
                key,
            )

    def publish_revision(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str, revision: str,
        lease_guard: tuple[str, str, int] | None = None,
    ) -> None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        key = (scope, owner, kb, revision)
        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_job_lease(db, lease_guard)
            documents = db.execute(
                "SELECT document_id FROM wiki_build_documents WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", key,
            ).fetchall()
            self._reject_tombstoned_documents(db, key, documents)
            run = db.execute(
                "SELECT status FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", key,
            ).fetchone()
            if not run:
                raise ValueError("Wiki revision does not exist")
            if run["status"] == "PUBLISHED":
                active = self._active_revision(db, scope, owner, kb)
                if active == revision:
                    return
                raise ValueError("Wiki revision is already published but no longer active")
            pages = db.execute(
                "SELECT r.page_id,r.page_type,r.status FROM wiki_page_revisions r "
                "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? AND r.revision=?",
                key,
            ).fetchall()
            if not pages:
                document_count = db.execute(
                    "SELECT COUNT(*) FROM wiki_build_documents WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=?", key,
                ).fetchone()[0]
                if document_count:
                    raise ValueError("Wiki revision has no pages")
            if any(row["status"] != "REVIEWING" for row in pages):
                raise ValueError("every Wiki page must pass review before publication")
            non_index = [row["page_id"] for row in pages if row["page_type"] != "INDEX"]
            for page_id in non_index:
                counts = db.execute(
                    "SELECT COUNT(*) AS total, SUM(CASE WHEN verdict='SUPPORTED' AND reason_code='ENTAILED' THEN 1 ELSE 0 END) AS ok "
                    "FROM wiki_page_claims WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=?",
                    (*key, page_id),
                ).fetchone()
                if not counts["total"] or counts["total"] != counts["ok"]:
                    raise ValueError("published Wiki pages require only supported sourced claims")
                claims = db.execute(
                    "SELECT claim_id,claim_text FROM wiki_page_claims WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=? AND page_id=?", (*key, page_id),
                ).fetchall()
                for claim in claims:
                    sources = {
                        row["source_id"] for row in db.execute(
                            "SELECT source_id FROM wiki_page_sources WHERE source_scope=? AND owner_id=? "
                            "AND knowledge_base_id=? AND revision=? AND page_id=? AND claim_id=?",
                            (*key, page_id, claim["claim_id"]),
                        )
                    }
                    audits = db.execute(
                        "SELECT claim_text,source_ids FROM wiki_claim_audits WHERE source_scope=? "
                        "AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=? "
                        "AND claim_id=? AND verdict='SUPPORTED' AND reason_code='ENTAILED'",
                        (*key, page_id, claim["claim_id"]),
                    ).fetchall()
                    if not any(
                        audit["claim_text"] == claim["claim_text"]
                        and set(json.loads(audit["source_ids"])) == sources
                        for audit in audits
                    ):
                        raise ValueError("published Wiki claims require an exact supported audit record")
            db.execute(
                "UPDATE wiki_build_runs SET status='STALE' WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND status='PUBLISHED'", (scope, owner, kb),
            )
            db.execute(
                "UPDATE wiki_page_revisions SET status='STALE' WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND status='PUBLISHED'", (scope, owner, kb),
            )
            db.execute(
                "UPDATE wiki_build_runs SET status='PUBLISHED',activated_at=? WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=? AND revision=?", (now, *key),
            )
            db.execute(
                "UPDATE wiki_page_revisions SET status='PUBLISHED' WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", key,
            )
            db.execute(
                "DELETE FROM wiki_pages_fts WHERE source_scope=? AND owner_id=? AND knowledge_base_id=?",
                (scope, owner, kb),
            )
            for row in db.execute(
                "SELECT r.page_id,r.title,r.slug,r.identity_id,r.summary,r.payload FROM wiki_page_revisions r "
                "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? AND r.revision=?",
                key,
            ).fetchall():
                page = json.loads(row["payload"])
                aliases = []
                if row["identity_id"]:
                    aliases = [value["alias"] for value in db.execute(
                        "SELECT alias FROM wiki_identity_aliases WHERE source_scope=? AND owner_id=? "
                        "AND knowledge_base_id=? AND revision=? AND identity_id=?",
                        (*key, row["identity_id"]),
                    ).fetchall()]
                claim_text = "\n".join(
                    claim["text"] for section in page.get("sections") or [] for claim in section.get("claims") or []
                )
                search_text = "\n".join([row["title"], row["slug"], *aliases, row["summary"], claim_text])
                db.execute(
                    "INSERT INTO wiki_pages_fts VALUES(?,?,?,?,?,?)",
                    (row["page_id"], scope, owner, kb, revision, search_text),
                )

    def search_pages(
        self, query: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, top_k: int = 8,
    ) -> list[dict[str, Any]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        query = query.strip()
        if not query:
            return []
        top_k = min(20, max(1, int(top_k)))
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return []
            terms = [term.replace('"', "") for term in query.split() if term][:20]
            rows: list[sqlite3.Row] = []
            if terms:
                try:
                    rows = db.execute(
                        "SELECT page_id,bm25(wiki_pages_fts) AS rank FROM wiki_pages_fts "
                        "WHERE wiki_pages_fts MATCH ? AND source_scope=? AND owner_id=? "
                        "AND knowledge_base_id=? AND revision=? ORDER BY rank LIMIT ?",
                        (" OR ".join(f'"{term}"' for term in terms), scope, owner, kb, revision, top_k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                rows = db.execute(
                    "SELECT r.page_id,0 AS rank FROM wiki_page_revisions r "
                    "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? "
                    "AND r.revision=? AND lower(r.title || ' ' || r.slug || ' ' || r.summary) LIKE ? LIMIT ?",
                    (scope, owner, kb, revision, f"%{query.casefold()}%", top_k),
                ).fetchall()
            return [self._page_summary(db, scope, owner, kb, revision, row["page_id"], rank) for rank, row in enumerate(rows, 1)]

    def active_vector_pages(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> tuple[str, list[dict[str, str]]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return "", []
        return revision, self.revision_vector_pages(
            source_scope=scope, owner_id=owner, knowledge_base_id=kb, revision=revision,
        )

    def revision_vector_pages(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        revision: str,
    ) -> list[dict[str, str]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            run = db.execute(
                "SELECT 1 FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND status IN ('DRAFT','PUBLISHED')",
                (scope, owner, kb, revision),
            ).fetchone()
            if run is None:
                raise ValueError("Wiki vector revision is unavailable")
            rows = db.execute(
                "SELECT page_id,title,summary,payload FROM wiki_page_revisions WHERE "
                "source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
                (scope, owner, kb, revision),
            ).fetchall()
            return [{
                "page_id": row["page_id"],
                "text": "\n".join([row["title"], row["summary"], *(
                    claim["text"] for section in json.loads(row["payload"]).get("sections") or []
                    for claim in section.get("claims") or []
                )]),
            } for row in rows]

    def replace_page_vectors(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        revision: str, model_id: str, vectors: list[tuple[str, bytes]],
    ) -> None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        if not model_id.strip():
            raise ValueError("Wiki vector model_id is required")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT status FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", (scope, owner, kb, revision),
            ).fetchone()
            if run is None or run["status"] not in {"DRAFT", "PUBLISHED"}:
                raise ValueError("Wiki vector revision changed during indexing")
            if run["status"] == "PUBLISHED" and self._active_revision(db, scope, owner, kb) != revision:
                raise ValueError("Wiki active revision changed during vector indexing")
            valid = {row["page_id"] for row in db.execute(
                "SELECT page_id FROM wiki_page_revisions WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", (scope, owner, kb, revision),
            )}
            if {page_id for page_id, _ in vectors} != valid or len(vectors) != len(valid):
                raise ValueError("Wiki vector index must cover the active revision exactly")
            db.execute(
                "DELETE FROM wiki_page_vectors WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND model_id=?",
                (scope, owner, kb, revision, model_id),
            )
            db.executemany(
                "INSERT INTO wiki_page_vectors VALUES(?,?,?,?,?,?,?)",
                [(* (scope, owner, kb, revision), page_id, model_id, value)
                 for page_id, value in vectors],
            )

    def search_page_vectors(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
        model_id: str, query_vector: bytes, top_k: int,
    ) -> list[dict[str, Any]]:
        import array
        import math

        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        query = array.array("f")
        query.frombytes(query_vector)
        if len(query) != 1024 or not all(math.isfinite(value) for value in query):
            raise ValueError("Wiki BGE-M3 query vector must be finite and 1024-dimensional")
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return []
            rows = db.execute(
                "SELECT page_id,embedding FROM wiki_page_vectors WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND model_id=?",
                (scope, owner, kb, revision, model_id),
            ).fetchall()
            scored = []
            for row in rows:
                vector = array.array("f")
                vector.frombytes(row["embedding"])
                if len(vector) != 1024:
                    raise ValueError("Wiki BGE-M3 index vector has wrong dimension")
                score = sum(left * right for left, right in zip(query, vector))
                scored.append((score, row["page_id"]))
            scored.sort(key=lambda item: (-item[0], item[1]))
            return [self._page_summary(db, scope, owner, kb, revision, page_id, rank)
                    for rank, (_score, page_id) in enumerate(scored[:top_k], 1)]

    def read_page(
        self, page_ref: str, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> dict[str, Any] | None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return None
            row = db.execute(
                "SELECT r.page_id,r.payload FROM wiki_page_revisions r "
                "WHERE r.source_scope=? AND r.owner_id=? AND r.knowledge_base_id=? "
                "AND r.revision=? AND (r.page_id=? OR r.slug=?)",
                (scope, owner, kb, revision, page_ref, page_ref),
            ).fetchone()
            if not row:
                return None
            page = json.loads(row["payload"])
            page["status"] = "PUBLISHED"
            page["citation_authority"] = False
            return page

    def read_sources(
        self, page_id: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, claim_id: str = "",
    ) -> list[dict[str, Any]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        with self.connection() as db:
            revision = self._active_revision(db, scope, owner, kb)
            if not revision:
                return []
            sql = (
                "SELECT claim_id,source_id,document_id,document_version_id,section_id,evidence_id,"
                "support_quote,quote_start,quote_end,evidence_sha256 FROM wiki_page_sources "
                "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=?"
            )
            params: tuple[Any, ...] = (scope, owner, kb, revision, page_id)
            if claim_id:
                sql += " AND claim_id=?"
                params = (*params, claim_id)
            sql += " ORDER BY claim_id,source_id"
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    @staticmethod
    def _active_revision(db: sqlite3.Connection, scope: str, owner: str, kb: str) -> str:
        row = db.execute(
            "SELECT r.revision FROM wiki_build_runs r WHERE r.source_scope=? AND r.owner_id=? "
            "AND r.knowledge_base_id=? AND r.status='PUBLISHED' AND NOT EXISTS ("
            "SELECT 1 FROM wiki_build_documents d JOIN wiki_source_tombstones t "
            "ON t.source_scope=d.source_scope AND t.owner_id=d.owner_id "
            "AND t.knowledge_base_id=d.knowledge_base_id AND t.document_id=d.document_id "
            "WHERE d.source_scope=r.source_scope AND d.owner_id=r.owner_id "
            "AND d.knowledge_base_id=r.knowledge_base_id AND d.revision=r.revision)",
            (scope, owner, kb),
        ).fetchone()
        return str(row["revision"]) if row else ""

    @staticmethod
    def _page_summary(
        db: sqlite3.Connection, scope: str, owner: str, kb: str,
        revision: str, page_id: str, rank: int,
    ) -> dict[str, Any]:
        row = db.execute(
            "SELECT r.page_id,r.page_type,r.slug,r.title,r.summary,r.document_version_ids "
            "FROM wiki_page_revisions r WHERE r.source_scope=? AND r.owner_id=? "
            "AND r.knowledge_base_id=? AND r.revision=? AND r.page_id=?",
            (scope, owner, kb, revision, page_id),
        ).fetchone()
        sources = db.execute(
            "SELECT DISTINCT document_version_id,section_id,evidence_id FROM wiki_page_sources "
            "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=?",
            (scope, owner, kb, revision, page_id),
        ).fetchall()
        return {
            "page_id": row["page_id"], "page_type": row["page_type"], "slug": row["slug"],
            "title": row["title"], "summary": row["summary"],
            "score": round(1.0 / (1.0 + 0.12 * (rank - 1)), 6),
            "document_version_ids": json.loads(row["document_version_ids"]),
            "section_ids": list(dict.fromkeys(item["section_id"] for item in sources if item["section_id"])),
            "evidence_ids": list(dict.fromkeys(item["evidence_id"] for item in sources)),
            "citation_authority": False,
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _source_id(source: dict[str, Any]) -> str:
    import hashlib
    raw = "\n".join([
        source["document_version_id"], source["evidence_id"],
        str(source["quote_start"]), str(source["quote_end"]),
    ])
    return "ws_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
