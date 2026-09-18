from pathlib import Path

from attachment_service.store import AttachmentStore


def _record(identifier: str = "ver_1", owner_id: str = "user-a") -> dict:
    return {
        "id": identifier, "filename": "policy.md", "mime_type": "text/markdown",
        "extension": ".md", "size_bytes": 10, "sha256": "a" * 64,
        "owner_id": owner_id, "dedupe_domain": owner_id, "scope": "library",
        "status": "ready", "vision_status": "not_requested", "blob_path": "x",
        "key_id": "k", "created_at": 1, "updated_at": 1,
        "knowledge_base_id": "kb-a", "document_id": "doc-a", "version_id": identifier,
        "source_scope": "personal", "active": 1, "version_number": 1,
    }


def test_section_rows_are_replaced_listed_and_purged(tmp_path: Path):
    store = AttachmentStore(tmp_path / "store.sqlite3")
    store.create_attachment(_record())
    store.replace_evidence("ver_1", [{
        "evidence_id": "ev-1", "source_type": "document_text", "content": "risk control",
        "locator": {}, "confidence": 1.0, "parser": "test",
    }])
    store.replace_sections("ver_1", [{
        "id": "sec-1", "version_id": "ver_1", "parent_id": None, "level": 0,
        "title": "Risk controls", "section_path": ["Policy", "Risk controls"],
        "summary": "risk control requirements", "evidence_ids": ["ev-1"],
        "quality": "high", "ordinal": 1,
    }])
    rows = store.list_sections(["ver_1"])
    assert len(rows) == 1
    assert rows[0]["evidence_ids"] == ["ev-1"]
    store.purge("ver_1")
    assert store.list_sections(["ver_1"]) == []


def test_section_listing_never_expands_beyond_requested_versions(tmp_path: Path):
    store = AttachmentStore(tmp_path / "store.sqlite3")
    store.create_attachment(_record("ver_a", "user-a"))
    store.create_attachment(_record("ver_b", "user-b"))
    for identifier in ("ver_a", "ver_b"):
        store.replace_sections(identifier, [{
            "id": f"sec_{identifier}", "version_id": identifier, "parent_id": None,
            "level": 1, "title": "Shared policy", "section_path": ["Shared policy"],
            "summary": "retention requirements", "evidence_ids": [f"ev_{identifier}"],
            "quality": "high", "ordinal": 1,
        }])

    hits = store.list_sections(["ver_a"])

    assert [item["version_id"] for item in hits] == ["ver_a"]
