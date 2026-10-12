from __future__ import annotations

import sqlite3
from pathlib import Path

from attachment_service.store import AttachmentStore
from shared_runtime.document_sections import build_navigation_text, normalize_section


def _attachment() -> dict:
    return {
        "id": "ver-1", "filename": "policy.md", "mime_type": "text/markdown",
        "extension": ".md", "size_bytes": 10, "sha256": "a" * 64,
        "owner_id": "user-1", "dedupe_domain": "user-1", "scope": "library",
        "status": "ready", "vision_status": "not_requested", "blob_path": "x",
        "key_id": "k", "created_at": 1, "updated_at": 1,
        "knowledge_base_id": "kb-1", "document_id": "doc-1", "version_id": "ver-1",
        "source_scope": "personal", "active": 1, "version_number": 1,
    }


def test_navigation_text_contains_document_ancestors_summaries_and_aliases() -> None:
    row = normalize_section(
        {
            "title": "访问控制", "section_path": ["安全", "访问控制"],
            "summary": "账号必须按最小权限分配。", "llm_summary": "Least privilege policy.",
        },
        version_id="ver-1", document_title="安全手册",
        page_ancestor_path=["RAG", "平台规范"], aliases=["ACL"],
    )

    assert row["navigation_text"] == build_navigation_text(
        row, document_title="安全手册", page_ancestor_path=["RAG", "平台规范"], aliases=["ACL"],
    )
    for value in ("安全手册", "平台规范", "访问控制", "最小权限", "Least privilege", "ACL"):
        assert value in row["navigation_text"]


def test_existing_section_table_receives_additive_migration(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE document_sections ("
        "id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, version_id TEXT NOT NULL, "
        "parent_id TEXT, level INTEGER NOT NULL, title TEXT NOT NULL, section_path TEXT NOT NULL, "
        "page_start INTEGER, page_end INTEGER, summary TEXT NOT NULL, evidence_ids TEXT NOT NULL, "
        "quality TEXT NOT NULL, ordinal INTEGER NOT NULL, created_at INTEGER NOT NULL)"
    )
    connection.commit()
    connection.close()

    store = AttachmentStore(database)
    columns = {
        row[1] for row in store.connection().execute("PRAGMA table_info(document_sections)")
    }

    assert {
        "extractive_summary", "llm_summary", "summary_model", "summary_prompt_version",
        "summary_input_hash", "summary_status", "own_block_ids", "subtree_block_ids",
        "navigation_text", "provenance", "line_start", "line_end",
    } <= columns


def test_evidence_fts_applies_section_scope_before_ranking(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "scope.sqlite3")
    store.create_attachment(_attachment())
    store.replace_evidence("ver-1", [
        {
            "evidence_id": "allowed", "source_type": "document_text",
            "content": "policy retention", "locator": {}, "confidence": 1.0, "parser": "test",
        },
        {
            "evidence_id": "outside", "source_type": "document_text",
            "content": "policy policy policy retention", "locator": {},
            "confidence": 1.0, "parser": "test",
        },
    ])

    hits = store.search_evidence(
        ["ver-1"], "policy retention", 5, evidence_ids=["allowed"],
    )

    assert [item["evidence_id"] for item in hits] == ["allowed"]
