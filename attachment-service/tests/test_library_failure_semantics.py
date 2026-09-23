from pathlib import Path

import pytest

from attachment_service.library_service import rebuild_library_projection, validate_library_configuration
from attachment_service.store import AttachmentStore


def _record(identifier: str = "ver_a"):
    return {
        "id": identifier,
        "filename": "report.md",
        "mime_type": "text/markdown",
        "extension": ".md",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "owner_id": "user-a",
        "dedupe_domain": "user:user-a",
        "scope": "library",
        "status": "ready",
        "blob_path": str(Path("blobs") / identifier),
        "key_id": "test",
        "created_at": 1,
        "updated_at": 1,
        "knowledge_base_id": "kb-a",
        "document_id": "doc-a",
        "version_id": identifier,
        "source_scope": "personal",
        "active": 1,
        "version_number": 1,
        "vector_ref": "ver_a__old",
    }


def _evidence(identifier: str, content: str):
    return [{
        "evidence_id": identifier,
        "source_type": "document_text",
        "content": content,
        "locator": {"section_path": ["Risk"]},
        "confidence": 1.0,
        "parser": "test",
    }]


class _FailingVector:
    def replace(self, *_):
        raise RuntimeError("milvus_insert_failure")


class _SuccessfulVector:
    def replace(self, ref, items):
        self.ref = ref
        self.items = items


def test_reindex_failure_keeps_old_active_projection(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record())
    store.replace_evidence("ver_a", _evidence("ver_a_chunk_0", "old searchable content"))

    with pytest.raises(RuntimeError, match="milvus_insert_failure"):
        rebuild_library_projection(
            store, _FailingVector(), store.get_attachment("ver_a"),
            _evidence("ver_a_chunk_0", "new content"), "job_new",
        )

    record = store.get_attachment("ver_a")
    assert record["active"] == 1
    assert record["status"] == "ready"
    assert record["vector_ref"] == "ver_a__old"
    assert store.list_evidence(["ver_a"])[0]["content"] == "old searchable content"


def test_successful_reindex_switches_generation_after_vector_build(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record())
    store.replace_evidence("ver_a", _evidence("ver_a_chunk_0", "old"))
    vector = _SuccessfulVector()

    previous, current = rebuild_library_projection(
        store, vector, store.get_attachment("ver_a"),
        _evidence("ver_a_chunk_0", "new"), "job_new",
    )

    assert previous == "ver_a__old"
    assert current == "ver_a__job_new"
    assert store.get_attachment("ver_a")["vector_ref"] == current
    assert store.list_evidence(["ver_a"])[0]["content"] == "new"


def test_cleanup_retry_does_not_change_active_version(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record())
    store.enqueue("cleanup-1", "ver_a", "cleanup_index", {"vector_ref": "stale-ref"})
    job = store.claim_job()
    store.requeue_job(job["id"], "cleanup_failed")

    active = store.list_library_versions("user-a", "kb-a")
    assert [item["id"] for item in active] == ["ver_a"]
    assert store.claim_job()["attempts"] == 1


def test_logical_delete_immediately_excludes_search_candidates(tmp_path):
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment(_record())
    store.soft_delete("ver_a")
    assert store.list_library_versions("user-a", "kb-a") == []


@pytest.mark.parametrize(
    ("library_enabled", "vector_enabled"),
    [(False, False), (False, True), (True, True)],
)
def test_library_configuration_accepts_supported_matrix(
    library_enabled: bool,
    vector_enabled: bool,
):
    validate_library_configuration(
        library_enabled=library_enabled,
        vector_enabled=vector_enabled,
    )


def test_library_enabled_without_vector_index_fails_fast():
    with pytest.raises(
        RuntimeError,
        match=(
            "PERSONAL_LIBRARY_ENABLED=true requires "
            "ATTACHMENT_VECTOR_INDEX_ENABLED=true"
        ),
    ):
        validate_library_configuration(library_enabled=True, vector_enabled=False)


def test_env_example_defines_personal_library_flag_once():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    definitions = [
        line
        for line in env_example.read_text(encoding="utf-8").splitlines()
        if line.startswith("PERSONAL_LIBRARY_ENABLED=")
    ]
    assert definitions == ["PERSONAL_LIBRARY_ENABLED=false"]
