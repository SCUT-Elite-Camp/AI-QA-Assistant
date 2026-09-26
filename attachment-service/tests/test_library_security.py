from pathlib import Path

from attachment_service.store import AttachmentStore


def _record(identifier: str, owner: str, kb: str, document: str, number: int, *, active: int = 0):
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
        "created_at": number,
        "updated_at": number,
        "knowledge_base_id": kb,
        "document_id": document,
        "version_id": identifier,
        "source_scope": "personal",
        "active": active,
        "version_number": number,
    }


def _evidence(identifier: str, content: str):
    return [{
        "evidence_id": f"{identifier}_chunk_0",
        "source_type": "document_text",
        "content": content,
        "locator": {},
        "confidence": 1.0,
        "parser": "test",
    }]


def test_owner_and_doc_filters_are_applied_before_lexical_candidates(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_a", "user-a", "kb-a", "doc-a", 1, active=1))
    store.create_attachment(_record("ver_b", "user-b", "kb-b", "doc-b", 1, active=1))
    store.replace_evidence("ver_a", _evidence("ver_a", "shared risk"))
    store.replace_evidence("ver_b", _evidence("ver_b", "shared risk " * 100))

    visible = store.list_library_versions("user-a", "kb-a", document_ids=["doc-a"])
    assert [item["id"] for item in visible] == ["ver_a"]
    assert store.list_library_versions("user-a", "kb-a", document_ids=["doc-b"]) == []
    assert [item["attachment_id"] for item in store.search_evidence(["ver_a"], "shared risk", 20)] == ["ver_a"]


def test_only_active_version_enters_candidates_after_chunk_count_shrinks(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record("ver_1", "user-a", "kb-a", "doc-a", 1, active=1))
    store.create_attachment(_record("ver_2", "user-a", "kb-a", "doc-a", 2))
    store.replace_evidence("ver_1", [
        _evidence(f"old_{index}", f"old-only token {index}")[0] for index in range(20)
    ])
    store.replace_evidence("ver_2", [
        _evidence(f"new_{index}", f"new-only token {index}")[0] for index in range(12)
    ])
    store.activate_library_version("ver_2", 2)

    visible = store.list_library_versions("user-a", "kb-a")
    assert [item["id"] for item in visible] == ["ver_2"]
    assert store.search_evidence(["ver_2"], "old-only", 50) == []
    assert len(store.search_evidence(["ver_2"], "new-only", 50)) == 12
