from __future__ import annotations

from shared_runtime.document_sections import stable_document_version_id


def test_document_version_identity_is_path_independent_and_scope_bound() -> None:
    fields = {
        "knowledge_base_id": "space-1",
        "document_id": "page-42",
        "version": 7,
        "content_sha256": "a" * 64,
    }

    enterprise = stable_document_version_id(source_scope="enterprise", **fields)
    moved_copy = stable_document_version_id(source_scope="ENTERPRISE", **fields)
    personal = stable_document_version_id(source_scope="personal", **fields)

    assert enterprise == moved_copy
    assert enterprise != personal
    assert enterprise.startswith("ver_")
