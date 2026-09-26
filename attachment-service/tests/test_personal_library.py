from pathlib import Path

from attachment_service.store import AttachmentStore


def _record(
    identifier: str,
    owner: str,
    kb: str,
    document: str,
    *,
    active: int = 0,
    version_number: int = 1,
):
    return {
        "id": identifier,
        "filename": f"{identifier}.md",
        "mime_type": "text/markdown",
        "extension": ".md",
        "size_bytes": 10,
        "sha256": identifier.ljust(64, "0")[:64],
        "owner_id": owner,
        "dedupe_domain": f"user:{owner}",
        "scope": "library",
        "status": "ready",
        "blob_path": str(Path("blobs") / identifier),
        "key_id": "test",
        "created_at": 1,
        "updated_at": 1,
        "knowledge_base_id": kb,
        "document_id": document,
        "version_id": identifier,
        "source_scope": "personal",
        "active": active,
        "version_number": version_number,
    }


def test_library_scope_and_active_version_are_enforced(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_a1", "user-a", "kb-a", "doc-a", active=1))
    store.create_attachment(_record("ver_a2", "user-a", "kb-a", "doc-a", version_number=2))
    store.create_attachment(_record("ver_b1", "user-b", "kb-b", "doc-b", active=1))

    result = store.activate_library_version("ver_a2", 2)

    assert result["stale_ids"] == ["ver_a1"]
    visible_a = store.list_library_versions("user-a", "kb-a")
    assert [item["id"] for item in visible_a] == ["ver_a2"]
    assert store.list_library_versions("user-b", "kb-a") == []
    assert store.list_library_versions("user-a", "kb-a", document_ids=["doc-b"]) == []


def test_soft_deleted_library_version_never_enters_candidates(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_a1", "user-a", "kb-a", "doc-a", active=1))
    store.soft_delete("ver_a1")
    assert store.list_library_versions("user-a", "kb-a") == []


def test_bm25_scope_is_applied_inside_fts_query(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_a1", "user-a", "kb-a", "doc-a", active=1))
    store.create_attachment(_record("ver_b1", "user-b", "kb-b", "doc-b", active=1))
    store.replace_evidence("ver_a1", [{
        "evidence_id": "ev-a", "source_type": "text", "content": "shared risk",
        "locator": {}, "confidence": 1.0, "parser": "test",
    }])
    store.replace_evidence("ver_b1", [{
        "evidence_id": f"ev-b-{index}", "source_type": "text",
        "content": "shared risk " * 100, "locator": {},
        "confidence": 1.0, "parser": "test",
    } for index in range(60)])

    results = store.search_evidence(["ver_a1"], "shared risk", top_k=1)

    assert [item["evidence_id"] for item in results] == ["ev-a"]
