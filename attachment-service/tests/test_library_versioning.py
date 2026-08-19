from pathlib import Path

from attachment_service.store import AttachmentStore


def _record(identifier: str, version_number: int, *, active: int = 0, status: str = "ready"):
    return {
        "id": identifier,
        "filename": f"{identifier}.md",
        "mime_type": "text/markdown",
        "extension": ".md",
        "size_bytes": 10,
        "sha256": identifier.ljust(64, "0")[:64],
        "owner_id": "user-a",
        "dedupe_domain": "user:user-a",
        "scope": "library",
        "status": status,
        "blob_path": str(Path("blobs") / identifier),
        "key_id": "test",
        "created_at": version_number,
        "updated_at": version_number,
        "knowledge_base_id": "kb-a",
        "document_id": "doc-a",
        "version_id": identifier,
        "source_scope": "personal",
        "active": active,
        "version_number": version_number,
    }


def test_older_version_cannot_automatically_replace_newer_active(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_2", 2))
    store.create_attachment(_record("ver_3", 3))

    assert store.activate_library_version("ver_3", 3)["activated"] is True
    result = store.activate_library_version("ver_2", 2)

    assert result == {"activated": False, "active_id": "ver_3", "stale_ids": []}
    assert store.list_library_versions("user-a", "kb-a")[0]["id"] == "ver_3"


def test_explicit_historical_reactivation_supports_a_b_a(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_a", 1))
    store.create_attachment(_record("ver_b", 2))
    store.activate_library_version("ver_b", 2)

    result = store.activate_library_version("ver_a", 1, explicit=True)

    assert result["activated"] is True
    assert result["stale_ids"] == ["ver_b"]
    assert store.list_library_versions("user-a", "kb-a")[0]["id"] == "ver_a"


def test_failed_version_cannot_be_activated(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_failed", 2, status="failed"))
    try:
        store.activate_library_version("ver_failed", 2)
    except ValueError as exc:
        assert str(exc) == "library_version_not_ready"
    else:
        raise AssertionError("failed version was activated")
