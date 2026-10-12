from pathlib import Path

from attachment_service.store import AttachmentStore


def test_evidence_revision_uses_optimistic_lock_and_updates_search(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db")
    now = 1
    store.create_attachment({
        "id": "att_1", "filename": "a.png", "mime_type": "image/png", "extension": ".png",
        "size_bytes": 10, "sha256": "a" * 64, "owner_id": "u1", "dedupe_domain": "u:u1",
        "scope": "chat", "status": "ready", "blob_path": "none", "key_id": "v1",
        "created_at": now, "updated_at": now,
    })
    store.replace_evidence("att_1", [{
        "evidence_id": "aev_1", "source_type": "ocr_text", "content": "错误码 DB-104Z",
        "locator": {"page": 1}, "confidence": 0.6, "parser": "test",
    }])
    assert store.revise_evidence("att_other", "aev_1", 1, "wrong", "", "u1", "rev_scope") is None
    assert store.revise_evidence("att_1", "aev_1", 2, "wrong", "", "u1", "rev_bad") is None
    updated = store.revise_evidence("att_1", "aev_1", 1, "错误码 DB-1042", "OCR修正", "u1", "rev_1")
    assert updated and updated[0]["version"] == 2
    assert updated[0]["confirmed"] is True
    assert updated[0]["original_content"] == "错误码 DB-104Z"
    assert updated[0]["content"] == "错误码 DB-1042"
    assert store.list_revisions("att_other", "aev_1") == []
    assert store.list_revisions("att_1", "aev_1")[0]["actor_id"] == "u1"


def test_blob_dedupe_is_scoped_and_reference_counted(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db")
    first = store.acquire_blob("blob_1", "topic:t1", "a" * 64, "one.blob", "v1")
    second = store.acquire_blob("ignored", "topic:t1", "a" * 64, "two.blob", "v1")
    other_space = store.acquire_blob("blob_2", "topic:t2", "a" * 64, "three.blob", "v1")
    assert first["storage_key"] == second["storage_key"]
    assert other_space["storage_key"] != first["storage_key"]
    assert store.release_blob("topic:t1", "a" * 64) is None
    assert store.release_blob("topic:t1", "a" * 64) == "one.blob"


def test_attachment_state_machine_rejects_invalid_transition(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db")
    store.create_attachment({
        "id": "att_state", "filename": "a.txt", "mime_type": "text/plain", "extension": ".txt",
        "size_bytes": 1, "sha256": "b" * 64, "owner_id": "u1", "dedupe_domain": "user:u1",
        "scope": "chat", "status": "scanning", "blob_path": "a.blob", "key_id": "v1",
        "created_at": 1, "updated_at": 1,
    })
    store.transition_attachment("att_state", "parsing")
    store.transition_attachment("att_state", "ready")
    try:
        store.transition_attachment("att_state", "quarantined")
        raise AssertionError("invalid transition must be rejected")
    except ValueError as error:
        assert "invalid_attachment_transition" in str(error)


def test_vision_state_machine_requires_queued_before_running(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db")
    store.create_attachment({
        "id": "att_vision", "filename": "a.png", "mime_type": "image/png", "extension": ".png",
        "size_bytes": 1, "sha256": "c" * 64, "owner_id": "u1", "dedupe_domain": "user:u1",
        "scope": "chat", "status": "ready", "blob_path": "a.blob", "key_id": "v1",
        "created_at": 1, "updated_at": 1,
    })
    try:
        store.transition_vision("att_vision", "running")
        raise AssertionError("vision must enter queued before running")
    except ValueError as error:
        assert "invalid_vision_transition" in str(error)
    store.transition_vision("att_vision", "queued")
    store.transition_vision("att_vision", "running")
    store.transition_vision("att_vision", "ready")


def test_store_recovery_marks_interrupted_vision_as_retryable(tmp_path: Path) -> None:
    database = tmp_path / "attachments.db"
    store = AttachmentStore(database)
    store.create_attachment({
        "id": "att_interrupted", "filename": "a.png", "mime_type": "image/png",
        "extension": ".png", "size_bytes": 1, "sha256": "d" * 64,
        "owner_id": "u1", "dedupe_domain": "user:u1", "scope": "chat",
        "status": "ready", "blob_path": "a.blob", "key_id": "v1",
        "created_at": 1, "updated_at": 1,
    })
    store.transition_vision("att_interrupted", "queued")
    store.transition_vision("att_interrupted", "running")
    store.connection().close()

    recovered = AttachmentStore(database)

    assert recovered.get_attachment("att_interrupted")["vision_status"] == "failed"
    recovered.transition_vision("att_interrupted", "queued")


def test_indexable_attachments_exclude_nonready_and_deleted_records(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db")
    for attachment_id, status in (
        ("att_ready", "ready"),
        ("att_review", "needs_review"),
        ("att_parsing", "parsing"),
        ("att_deleted", "deleted"),
    ):
        store.create_attachment({
            "id": attachment_id, "filename": f"{attachment_id}.txt", "mime_type": "text/plain",
            "extension": ".txt", "size_bytes": 1, "sha256": attachment_id.ljust(64, "a"),
            "owner_id": "u1", "dedupe_domain": f"user:{attachment_id}", "scope": "chat",
            "status": status, "blob_path": f"{attachment_id}.blob", "key_id": "v1",
            "created_at": 1, "updated_at": 1,
        })

    assert store.list_indexable_attachment_ids() == ["att_ready", "att_review"]
