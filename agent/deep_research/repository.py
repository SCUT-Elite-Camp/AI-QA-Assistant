"""SQLite authoritative repository for the Deep Research control plane."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterable

from agent.schemas.research import (
    ResearchApproval,
    ResearchJob,
    ResearchJobStatus,
    ResearchPlan,
    ResearchPlanStatus,
    ResearchTask,
    SourceManifest,
)


class ResearchRepositoryError(RuntimeError):
    """Base error for durable Research state operations."""


class ResearchNotFoundError(ResearchRepositoryError):
    """A requested Research entity does not exist."""


class ResearchConflictError(ResearchRepositoryError):
    """A write conflicts with an immutable or versioned Research entity."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteResearchRepository:
    """Persist Research business entities in one SQLite database.

    The repository is deliberately the source of truth.  A future graph
    checkpoint should only contain cursors and entity IDs, never a second copy
    of this business state.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if self.database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_jobs (
                    research_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    plan_version INTEGER,
                    manifest_hash TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_jobs_status
                    ON research_jobs(status, updated_at);

                CREATE TABLE IF NOT EXISTS research_manifests (
                    research_id TEXT PRIMARY KEY,
                    manifest_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research_jobs(research_id)
                );

                CREATE TABLE IF NOT EXISTS research_plans (
                    research_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(research_id, version),
                    FOREIGN KEY(research_id) REFERENCES research_jobs(research_id)
                );

                CREATE TABLE IF NOT EXISTS research_tasks (
                    research_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(research_id, plan_version, task_id),
                    FOREIGN KEY(research_id, plan_version)
                        REFERENCES research_plans(research_id, version)
                );

                CREATE TABLE IF NOT EXISTS research_approvals (
                    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research_jobs(research_id)
                );

                CREATE INDEX IF NOT EXISTS idx_research_approvals_lookup
                    ON research_approvals(research_id, plan_version, approved_at);
                """
            )

    def create_job(self, job: ResearchJob) -> ResearchJob:
        """Insert a new durable Job before any asynchronous work is started."""

        with self._lock, self._connection:
            try:
                self._connection.execute(
                    """
                    INSERT INTO research_jobs(
                        research_id, status, plan_version, manifest_hash,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._job_row(job),
                )
            except sqlite3.IntegrityError as exc:
                raise ResearchConflictError(
                    f"research job '{job.research_id}' already exists"
                ) from exc
        return job

    def get_job(self, research_id: str) -> ResearchJob:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM research_jobs WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        if row is None:
            raise ResearchNotFoundError(f"research job '{research_id}' not found")
        return ResearchJob.model_validate_json(row["payload_json"])

    def list_jobs(
        self,
        statuses: Iterable[ResearchJobStatus] | None = None,
    ) -> list[ResearchJob]:
        with self._lock:
            if statuses:
                values = [status.value for status in statuses]
                placeholders = ",".join("?" for _ in values)
                rows = self._connection.execute(
                    f"SELECT payload_json FROM research_jobs "
                    f"WHERE status IN ({placeholders}) ORDER BY created_at",
                    values,
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT payload_json FROM research_jobs ORDER BY created_at"
                ).fetchall()
        return [ResearchJob.model_validate_json(row["payload_json"]) for row in rows]

    def update_job(self, job: ResearchJob) -> ResearchJob:
        updated = job.model_copy(update={"updated_at": _now()})
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE research_jobs
                SET status = ?, plan_version = ?, manifest_hash = ?,
                    payload_json = ?, updated_at = ?
                WHERE research_id = ?
                """,
                self._job_row(updated, include_id_last=True),
            )
            if cursor.rowcount != 1:
                raise ResearchNotFoundError(
                    f"research job '{updated.research_id}' not found"
                )
        return updated

    def transition_job(
        self,
        research_id: str,
        *,
        expected_statuses: Iterable[ResearchJobStatus],
        status: ResearchJobStatus,
        current_stage: str | None = None,
        **updates,
    ) -> ResearchJob | None:
        """Atomically claim a Job if it is still in an expected state."""

        expected = tuple(item.value for item in expected_statuses)
        if not expected:
            raise ValueError("expected_statuses must not be empty")
        with self._lock, self._connection:
            placeholders = ",".join("?" for _ in expected)
            row = self._connection.execute(
                "SELECT payload_json, status FROM research_jobs WHERE research_id = ?",
                (research_id,),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(f"research job '{research_id}' not found")
            if row["status"] not in expected:
                return None

            job = ResearchJob.model_validate_json(row["payload_json"])
            payload = job.model_dump()
            payload.update(updates)
            payload["status"] = status
            payload["current_stage"] = current_stage or status.value
            payload["updated_at"] = _now()
            updated = ResearchJob.model_validate(payload)
            cursor = self._connection.execute(
                f"""
                UPDATE research_jobs
                SET status = ?, plan_version = ?, manifest_hash = ?,
                    payload_json = ?, updated_at = ?
                WHERE research_id = ? AND status IN ({placeholders})
                """,
                (
                    updated.status.value,
                    updated.plan_version,
                    updated.manifest_hash,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    research_id,
                    *expected,
                ),
            )
            if cursor.rowcount != 1:
                return None
        return updated

    def save_manifest(self, manifest: SourceManifest) -> SourceManifest:
        payload = manifest.model_dump_json()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT manifest_hash, payload_json FROM research_manifests WHERE research_id = ?",
                (manifest.research_id,),
            ).fetchone()
            if existing is not None:
                if existing["manifest_hash"] != manifest.manifest_hash:
                    raise ResearchConflictError(
                        f"SourceManifest for '{manifest.research_id}' is immutable"
                    )
                return SourceManifest.model_validate_json(existing["payload_json"])

            try:
                self._connection.execute(
                    """
                    INSERT INTO research_manifests(
                        research_id, manifest_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        manifest.research_id,
                        manifest.manifest_hash,
                        payload,
                        manifest.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResearchNotFoundError(
                    f"research job '{manifest.research_id}' must exist before its manifest"
                ) from exc
        return manifest

    def get_manifest(self, research_id: str) -> SourceManifest:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM research_manifests WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        if row is None:
            raise ResearchNotFoundError(
                f"SourceManifest for '{research_id}' not found"
            )
        return SourceManifest.model_validate_json(row["payload_json"])

    def save_plan(self, plan: ResearchPlan) -> ResearchPlan:
        payload = plan.model_dump_json()
        now = _now().isoformat()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload_json FROM research_plans WHERE research_id = ? AND version = ?",
                (plan.research_id, plan.version),
            ).fetchone()
            if existing is not None:
                existing_plan = ResearchPlan.model_validate_json(existing["payload_json"])
                if existing_plan.model_dump() != plan.model_dump():
                    raise ResearchConflictError(
                        f"ResearchPlan v{plan.version} for '{plan.research_id}' is immutable"
                    )
                return existing_plan

            self._connection.execute(
                """
                INSERT INTO research_plans(
                    research_id, version, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.research_id,
                    plan.version,
                    plan.status.value,
                    payload,
                    now,
                    now,
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO research_tasks(
                    research_id, plan_version, task_id, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        plan.research_id,
                        plan.version,
                        task.task_id,
                        task.model_dump_json(),
                    )
                    for task in plan.tasks
                ],
            )
        return plan

    def get_plan(self, research_id: str, version: int | None = None) -> ResearchPlan:
        with self._lock:
            if version is None:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM research_plans
                    WHERE research_id = ? ORDER BY version DESC LIMIT 1
                    """,
                    (research_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM research_plans
                    WHERE research_id = ? AND version = ?
                    """,
                    (research_id, version),
                ).fetchone()
        if row is None:
            suffix = "" if version is None else f" v{version}"
            raise ResearchNotFoundError(
                f"ResearchPlan{suffix} for '{research_id}' not found"
            )
        return ResearchPlan.model_validate_json(row["payload_json"])

    def update_plan_status(self, plan: ResearchPlan) -> ResearchPlan:
        """Update only the lifecycle status of an existing immutable Plan."""

        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT payload_json FROM research_plans
                WHERE research_id = ? AND version = ?
                """,
                (plan.research_id, plan.version),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(
                    f"ResearchPlan v{plan.version} for '{plan.research_id}' not found"
                )
            existing = ResearchPlan.model_validate_json(row["payload_json"])
            if existing.model_dump(exclude={"status"}) != plan.model_dump(exclude={"status"}):
                raise ResearchConflictError(
                    f"ResearchPlan v{plan.version} content is immutable"
                )
            now = _now().isoformat()
            self._connection.execute(
                """
                UPDATE research_plans
                SET status = ?, payload_json = ?, updated_at = ?
                WHERE research_id = ? AND version = ?
                """,
                (
                    plan.status.value,
                    plan.model_dump_json(),
                    now,
                    plan.research_id,
                    plan.version,
                ),
            )
        return plan

    def commit_approval(
        self,
        approval: ResearchApproval,
        plan: ResearchPlan,
        ready_job: ResearchJob,
    ) -> ResearchJob:
        """Atomically persist Approval, Plan status, and Job=ready.

        Keeping these three writes in one SQLite transaction prevents a crash
        from leaving an auditable approval without a runnable Job (or the
        reverse).
        """

        if plan.status != ResearchPlanStatus.APPROVED:
            raise ValueError("plan must be approved before commit")
        if ready_job.status != ResearchJobStatus.READY:
            raise ValueError("job must be ready before approval commit")

        with self._lock, self._connection:
            job_row = self._connection.execute(
                "SELECT payload_json, status FROM research_jobs WHERE research_id = ?",
                (ready_job.research_id,),
            ).fetchone()
            if job_row is None:
                raise ResearchNotFoundError(
                    f"research job '{ready_job.research_id}' not found"
                )
            if job_row["status"] != ResearchJobStatus.AWAITING_APPROVAL.value:
                raise ResearchConflictError(
                    "Research Job is no longer awaiting approval"
                )

            plan_row = self._connection.execute(
                """
                SELECT payload_json FROM research_plans
                WHERE research_id = ? AND version = ?
                """,
                (plan.research_id, plan.version),
            ).fetchone()
            if plan_row is None:
                raise ResearchNotFoundError(
                    f"ResearchPlan v{plan.version} for '{plan.research_id}' not found"
                )
            existing_plan = ResearchPlan.model_validate_json(plan_row["payload_json"])
            if existing_plan.model_dump(exclude={"status"}) != plan.model_dump(
                exclude={"status"}
            ):
                raise ResearchConflictError("ResearchPlan content is immutable")

            existing_approval = self._connection.execute(
                """
                SELECT payload_json FROM research_approvals
                WHERE research_id = ? AND plan_version = ?
                ORDER BY approved_at DESC LIMIT 1
                """,
                (approval.research_id, approval.plan_version),
            ).fetchone()
            if existing_approval is not None:
                previous = ResearchApproval.model_validate_json(
                    existing_approval["payload_json"]
                )
                if previous.model_dump() != approval.model_dump():
                    raise ResearchConflictError(
                        "an approval already exists for this plan version"
                    )
            else:
                self._connection.execute(
                    """
                    INSERT INTO research_approvals(
                        research_id, plan_version, manifest_hash, payload_json, approved_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        approval.research_id,
                        approval.plan_version,
                        approval.manifest_hash,
                        approval.model_dump_json(),
                        approval.approved_at.isoformat(),
                    ),
                )

            now = _now().isoformat()
            self._connection.execute(
                """
                UPDATE research_plans
                SET status = ?, payload_json = ?, updated_at = ?
                WHERE research_id = ? AND version = ?
                """,
                (
                    plan.status.value,
                    plan.model_dump_json(),
                    now,
                    plan.research_id,
                    plan.version,
                ),
            )
            committed_job = ResearchJob.model_validate(
                {**ready_job.model_dump(), "updated_at": _now()}
            )
            cursor = self._connection.execute(
                """
                UPDATE research_jobs
                SET status = ?, plan_version = ?, manifest_hash = ?,
                    payload_json = ?, updated_at = ?
                WHERE research_id = ? AND status = ?
                """,
                (
                    committed_job.status.value,
                    committed_job.plan_version,
                    committed_job.manifest_hash,
                    committed_job.model_dump_json(),
                    committed_job.updated_at.isoformat(),
                    committed_job.research_id,
                    ResearchJobStatus.AWAITING_APPROVAL.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchConflictError(
                    "Research Job changed while approval was being committed"
                )
        return committed_job

    def get_tasks(
        self,
        research_id: str,
        plan_version: int | None = None,
    ) -> list[ResearchTask]:
        plan = self.get_plan(research_id, plan_version)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM research_tasks
                WHERE research_id = ? AND plan_version = ?
                ORDER BY rowid
                """,
                (research_id, plan.version),
            ).fetchall()
        if rows:
            return [ResearchTask.model_validate_json(row["payload_json"]) for row in rows]
        return list(plan.tasks)

    def save_approval(self, approval: ResearchApproval) -> ResearchApproval:
        with self._lock, self._connection:
            existing = self._connection.execute(
                """
                SELECT payload_json FROM research_approvals
                WHERE research_id = ? AND plan_version = ?
                ORDER BY approved_at DESC LIMIT 1
                """,
                (approval.research_id, approval.plan_version),
            ).fetchone()
            if existing is not None:
                existing_approval = ResearchApproval.model_validate_json(existing["payload_json"])
                if (
                    existing_approval.manifest_hash != approval.manifest_hash
                    or existing_approval.approved_by != approval.approved_by
                ):
                    raise ResearchConflictError(
                        "an approval already exists for this plan version"
                    )
                return existing_approval
            self._connection.execute(
                """
                INSERT INTO research_approvals(
                    research_id, plan_version, manifest_hash, payload_json, approved_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    approval.research_id,
                    approval.plan_version,
                    approval.manifest_hash,
                    approval.model_dump_json(),
                    approval.approved_at.isoformat(),
                ),
            )
        return approval

    def get_approval(
        self,
        research_id: str,
        plan_version: int | None = None,
    ) -> ResearchApproval:
        with self._lock:
            if plan_version is None:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM research_approvals
                    WHERE research_id = ? ORDER BY approved_at DESC LIMIT 1
                    """,
                    (research_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM research_approvals
                    WHERE research_id = ? AND plan_version = ?
                    ORDER BY approved_at DESC LIMIT 1
                    """,
                    (research_id, plan_version),
                ).fetchone()
        if row is None:
            raise ResearchNotFoundError(f"approval for '{research_id}' not found")
        return ResearchApproval.model_validate_json(row["payload_json"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteResearchRepository":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _job_row(job: ResearchJob, *, include_id_last: bool = False) -> tuple:
        values = (
            job.research_id,
            job.status.value,
            job.plan_version,
            job.manifest_hash,
            job.model_dump_json(),
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
        )
        if include_id_last:
            return (
                job.status.value,
                job.plan_version,
                job.manifest_hash,
                job.model_dump_json(),
                job.updated_at.isoformat(),
                job.research_id,
            )
        return values


__all__ = [
    "ResearchConflictError",
    "ResearchNotFoundError",
    "ResearchRepositoryError",
    "SQLiteResearchRepository",
]
