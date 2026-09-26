from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace
import pytest

from pipeline.wiki.domain import WikiScope
from pipeline.wiki.queue import WikiJobStage, WikiLifecycleCoordinator, next_wiki_stage
from storage.wiki_store import WikiStore


def _enqueue(store: WikiStore, *, max_attempts: int = 3) -> str:
    return store.enqueue_wiki_job(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
        document_id="doc", document_version_id="ver-1", content_sha256="a" * 64,
        payload={"reason": "ingest"}, max_attempts=max_attempts,
    )


def test_persistent_job_lease_recovers_and_advances(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    job_id = _enqueue(store)
    assert _enqueue(store) == job_id
    now = int(time.time())

    first = store.lease_wiki_job(worker_id="worker-a", lease_seconds=10, now=now)
    assert first and first["stage"] == "EXTRACT" and first["attempt"] == 1
    assert store.lease_wiki_job(worker_id="worker-b", now=now + 5) is None

    recovered = store.lease_wiki_job(worker_id="worker-b", lease_seconds=10, now=now + 11)
    assert recovered and recovered["job_id"] == job_id and recovered["attempt"] == 2
    store.advance_wiki_job(job_id, worker_id="worker-b", next_stage=WikiJobStage.CITE)
    next_lease = store.lease_wiki_job(worker_id="worker-c", now=now + 12)
    assert next_lease and next_lease["stage"] == "CITE"


def test_worker_lease_stays_within_configured_knowledge_base(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    first = _enqueue(store)
    second = store.enqueue_wiki_job(
        source_scope="enterprise", owner_id="", knowledge_base_id="another-kb",
        document_id="doc", document_version_id="ver-1", content_sha256="a" * 64,
    )
    lease = store.lease_wiki_job(
        worker_id="worker", source_scope="enterprise", owner_id="",
        knowledge_base_id="another-kb",
    )
    assert lease and lease["job_id"] == second
    with store.connection() as db:
        assert db.execute("SELECT status FROM wiki_jobs WHERE job_id=?", (first,)).fetchone()[0] == "PENDING"


def test_same_second_scope_jobs_keep_insertion_order(tmp_path, monkeypatch) -> None:
    from storage import wiki_store

    monkeypatch.setattr(wiki_store.time, "time", lambda: 1000)
    store = WikiStore(tmp_path / "wiki.sqlite3")
    ids = [(hashlib.sha256(f"enterprise\n\nkb\n{doc}\nv1\n{'a' * 64}".encode()).hexdigest(), doc)
           for doc in ("a", "b", "c", "d")]
    first_doc = max(ids)[1]
    second_doc = min(ids)[1]
    first = store.enqueue_wiki_job(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
        document_id=first_doc, document_version_id="v1", content_sha256="a" * 64,
    )
    store.enqueue_wiki_job(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
        document_id=second_doc, document_version_id="v1", content_sha256="a" * 64,
    )
    lease = store.lease_wiki_job(worker_id="worker", now=1000)
    assert lease and lease["job_id"] == first


def test_retry_dead_letter_and_coalesced_finalize_requests(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    job_id = _enqueue(store, max_attempts=1)
    lease = store.lease_wiki_job(worker_id="worker", now=int(time.time()))
    assert lease and lease["job_id"] == job_id
    store.fail_wiki_job(job_id, worker_id="worker", error="permanent", retry_at=200)

    store.upsert_pending_wiki_op(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
        document_id="doc", document_version_id="ver-1", content_sha256="a" * 64,
    )
    store.upsert_pending_wiki_op(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
        document_id="doc", document_version_id="ver-2", content_sha256="b" * 64,
    )
    store.request_wiki_finalize(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )
    store.request_wiki_finalize(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_dead_letters").fetchone()[0] == 1
        pending = db.execute("SELECT * FROM wiki_pending_ops").fetchone()
        assert pending["document_version_id"] == "ver-2" and pending["coalesced_count"] == 2
        finalize = db.execute("SELECT * FROM wiki_finalize_requests").fetchone()
        assert finalize["generation"] == 2 and finalize["status"] == "PENDING"

    assert next_wiki_stage(WikiJobStage.VERIFY) == WikiJobStage.FINALIZE
    assert next_wiki_stage(WikiJobStage.PUBLISH) is None


def test_slug_claim_allows_one_worker_and_recovers_after_expiry(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    context = {
        "source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb",
    }
    assert store.claim_wiki_slug("rag", worker_id="worker-a", now=100, **context)
    assert not store.claim_wiki_slug("rag", worker_id="worker-b", now=110, **context)
    assert store.claim_wiki_slug("rag", worker_id="worker-b", now=161, **context)
    assert not store.release_wiki_slug("rag", worker_id="worker-a", **context)
    assert store.release_wiki_slug("rag", worker_id="worker-b", **context)


def test_pending_updates_and_deletion_schedule_one_scope_job(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    common = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    store.upsert_pending_wiki_op(**common, document_id="a", document_version_id="v1",
                                 content_sha256="a" * 64)
    store.upsert_pending_wiki_op(**common, document_id="a", document_version_id="v2",
                                 content_sha256="b" * 64)
    store.upsert_pending_wiki_op(**common, document_id="b", document_version_id="v1",
                                 content_sha256="c" * 64, operation="DELETE")
    jobs = store.schedule_pending_wiki_jobs()
    assert len(jobs) == 1
    lease = store.lease_wiki_job(worker_id="worker")
    assert lease and lease["job_id"] == jobs[0]
    assert lease["payload"]["changes"] == [
        {"document_id": "a", "document_version_id": "v2", "content_sha256": "b" * 64,
         "op_type": "UPSERT"},
        {"document_id": "b", "document_version_id": "v1", "content_sha256": "c" * 64,
         "op_type": "DELETE"},
    ]
    assert store.schedule_pending_wiki_jobs() == []


def test_lifecycle_coordinator_records_ingest_and_deletion_without_publishing(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    coordinator = WikiLifecycleCoordinator(store)
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    coordinator.document_ingested(SimpleNamespace(
        scope=scope, document_id="doc", document_version_id="v1",
        content_sha256="a" * 64,
    ))
    coordinator.document_deleted(scope=scope, document_id="doc", document_version_id="v1")
    jobs = coordinator.schedule(debounce_seconds=0)
    assert len(jobs) == 1
    lease = store.lease_wiki_job(worker_id="worker")
    assert lease and lease["payload"]["intent"] == "PREVIEW"
    assert lease["payload"]["changes"][0]["op_type"] == "DELETE"
    assert store.search_pages("doc", source_scope="enterprise", owner_id="",
                              knowledge_base_id="kb") == []


def test_expired_worker_cannot_advance_or_publish_after_takeover(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    job_id = _enqueue(store)
    now = int(time.time())
    old = store.lease_wiki_job(worker_id="old", lease_seconds=10, now=now)
    assert old and store.renew_wiki_job_lease(job_id, worker_id="old", attempt=1)
    with store.connection() as db:
        db.execute("UPDATE wiki_jobs SET lease_expires_at=? WHERE job_id=?", (now - 1, job_id))
    new = store.lease_wiki_job(worker_id="new", lease_seconds=10, now=now)
    assert new and new["attempt"] == 2
    assert not store.renew_wiki_job_lease(job_id, worker_id="old", attempt=1)
    with pytest.raises(ValueError, match="not leased"):
        store.advance_wiki_job(job_id, worker_id="old", next_stage=WikiJobStage.CITE,
                               attempt=1)
    with pytest.raises(ValueError, match="lease was lost"):
        store.publish_revision(source_scope="enterprise", owner_id="",
                               knowledge_base_id="kb", revision="not-yet-built",
                               lease_guard=(job_id, "old", 1))
