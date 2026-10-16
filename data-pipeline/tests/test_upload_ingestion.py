"""Upload parses survive restart and feed the canonical structured ingestion."""
import hashlib
import json

import pytest

from data_persistence.private_files import AttachmentStore
from pipeline.files.parsing import parse_context
from pipeline.files.evidence import prepare_persisted_document
from pipeline.ingestion.uploads import ingest_persisted_document


def record(path, *, scope="library"):
    return {
        "id": "ver_a", "filename": path.name, "mime_type": "text/plain",
        "extension": path.suffix, "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "owner_id": "alice", "dedupe_domain": "user:alice", "scope": scope,
        "status": "parsing", "blob_path": str(path), "key_id": "test",
        "created_at": 1, "updated_at": 1, "knowledge_base_id": "kb_a",
        "document_id": "doc_a", "version_id": "ver_a", "source_scope": "personal",
    }


def parsed_fixture(tmp_path, text, extension=".md", *, scope="library"):
    path = tmp_path / ("upload" + extension)
    path.write_text(text, encoding="utf-8")
    source = record(path, scope=scope)
    store = AttachmentStore(tmp_path / "private.sqlite3")
    store.create_attachment(source)
    parsed = parse_context(path, source["id"])
    store.save_parsed_document(source["id"], parsed)
    return store, source, path


def test_parse_is_index_free_and_restart_ingests_snapshot_without_raw_file(tmp_path):
    store, source, path = parsed_fixture(tmp_path, "# Scope\n" + "Details. " * 100 + "\n## Controls\nSentinel tail text.")
    assert store.list_evidence([source["id"]]) == []
    path.unlink()
    restored = AttachmentStore(tmp_path / "private.sqlite3")
    job = restored.claim_job()
    assert job["kind"] == "ingest"
    snapshot = restored.load_parsed_document(source["id"])
    evidence, sections = prepare_persisted_document(snapshot, source)
    assert any("Sentinel tail text." in row["content"] for row in evidence)
    assert any(row["locator"]["section_path"] == ["Scope", "Controls"] for row in evidence)
    assert all(item["evidence_id"].startswith("ver_a_chunk_") for item in evidence)
    assert {row["evidence_id"] for row in evidence} <= set(sections[0]["evidence_ids"])
    assert prepare_persisted_document(json.loads(json.dumps(snapshot)), source) == (evidence, sections)


def test_context_storage_does_not_create_a_second_chat_vector_job(tmp_path):
    store, source, _ = parsed_fixture(tmp_path, "Immediate question context", ".txt", scope="chat")
    assert store.load_parsed_document(source["id"])["context"] == "Immediate question context"
    assert store.claim_job() is None


def test_hash_drift_and_deleted_uploads_cannot_be_ingested(tmp_path):
    store, source, path = parsed_fixture(tmp_path, "Trusted content", ".txt")
    snapshot = store.load_parsed_document(source["id"])
    with pytest.raises(ValueError, match="parsed_source_hash_mismatch"):
        prepare_persisted_document(snapshot, {**source, "sha256": "changed"})
    store.soft_delete(source["id"])
    with pytest.raises(ValueError, match="attachment_not_available"):
        store.save_parsed_document(source["id"], snapshot)


def test_table_and_sheet_provenance_survives_shared_chunking(tmp_path):
    import openpyxl
    path = tmp_path / "sales.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Region", "Amount"])
    sheet.append(["East", 120])
    workbook.save(path)
    source = record(path)
    parsed = {**parse_context(path, source["id"]), "source_sha256": source["sha256"]}
    evidence, _ = prepare_persisted_document(parsed, source)
    table = next(row for row in evidence if row["source_type"] == "table")
    assert table["locator"]["sheet"] == "Sales"
    assert table["locator"]["cell_range"] == "A1:B2"
    assert "East" in table["content"] and "120" in table["index_text"]


def test_failed_persistence_does_not_leave_an_ingestion_job(tmp_path, monkeypatch):
    store, source, _ = parsed_fixture(tmp_path, "content", ".txt", scope="chat")
    db = store.connection()
    db.execute("CREATE TRIGGER reject_parse BEFORE INSERT ON parsed_documents BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    with pytest.raises(Exception, match="blocked"):
        store.save_parsed_document(source["id"], {"context": "bad", "documents": [], "items": []})
    assert store.claim_job() is None
    assert store.load_parsed_document(source["id"])["context"] == "content"


def test_deletion_during_embedding_cannot_publish_or_reactivate_a_version(tmp_path, monkeypatch):
    store, source, _ = parsed_fixture(tmp_path, "# Heading\nDocument body")
    deleted_refs = []

    class Index:
        def delete_document_chunks(self, ref):
            deleted_refs.append(ref)

    monkeypatch.setattr("pipeline.ingestion.uploads.index_document_vectors", lambda *_: store.soft_delete(source["id"]))
    job = store.claim_job()
    with pytest.raises(RuntimeError, match="parse_cancelled"):
        ingest_persisted_document(store, Index(), source, job)
    assert store.get_attachment(source["id"], include_deleted=True)["status"] == "deleted"
    assert store.list_evidence([source["id"]]) == []
    assert len(deleted_refs) == 1
