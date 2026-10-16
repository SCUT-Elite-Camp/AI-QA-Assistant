from pathlib import Path

from data_persistence.private_files import AttachmentStore


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
