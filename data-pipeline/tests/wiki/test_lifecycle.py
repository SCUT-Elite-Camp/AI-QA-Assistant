from __future__ import annotations

import json

import pytest

from parsers.markdown_parser import MarkdownParser
from pipeline.chunker import chunk_from_blocks
from pipeline.structure import build_document_sections
from pipeline.wiki.lifecycle import WikiDocumentLifecycle, WikiDocumentProjection
from pipeline.wiki.source import document_to_wiki_source
from pipeline.wiki.domain import WikiScope
from storage.wiki_store import WikiStore
from shared_runtime.wiki_paths import resolve_wiki_db_path


def _document(number: int):
    text = f"# Meeting {number}\n\nThe team reviewed RAG retrieval and source evidence."
    doc = MarkdownParser().parse_text(
        text, source=f"meeting-{number}.md",
        metadata={"space_id": "kb", "page_id": str(number), "version": 1,
                  "title": f"Meeting {number}"},
    )
    doc.chunks = chunk_from_blocks(doc.content_blocks, doc.version_id,
                                   document_title=doc.title)
    doc.sections = build_document_sections(doc)
    return doc


def test_projection_uses_active_versioned_confluence_documents(tmp_path) -> None:
    doc = _document(1)
    (tmp_path / f"{doc.doc_id}.json").write_text(
        json.dumps(doc.model_dump(mode="json")), encoding="utf-8",
    )
    legacy = {**doc.model_dump(mode="json"), "metadata": {}, "version_id": ""}
    (tmp_path / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
    loaded = WikiDocumentProjection(tmp_path, knowledge_base_id="kb").active_documents()
    assert len(loaded["kb"]) == 1
    assert loaded["kb"][0].document_version_id == doc.version_id
    (tmp_path / f"{doc.doc_id}.json").write_text(
        json.dumps({**doc.model_dump(mode="json"), "version_id": ""}), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source requires document, version"):
        WikiDocumentProjection(tmp_path, knowledge_base_id="kb").active_documents()


def test_full_export_manifest_revokes_only_missing_pages(tmp_path) -> None:
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    export_dir = tmp_path / "confluence"
    space_dir = export_dir / "space"
    space_dir.mkdir(parents=True)
    first, second = _document(1), _document(2)
    for document in (first, second):
        (documents_dir / f"{document.doc_id}.json").write_text(
            json.dumps(document.model_dump(mode="json")), encoding="utf-8",
        )
    projection = WikiDocumentProjection(
        documents_dir, knowledge_base_id="kb", confluence_export_dir=export_dir,
    )
    manifest = {"source_type": "confluence_cloud", "space_id": "kb",
                "status": "partial", "full_sync": True,
                "pages": {"1": {}}}
    path = space_dir / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert len(projection.active_documents()["kb"]) == 2
    manifest["status"] = "ok"
    manifest["full_sync"] = False
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert len(projection.active_documents()["kb"]) == 2
    manifest["full_sync"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert {item.document_id for item in projection.active_documents()["kb"]} == {first.doc_id}
    manifest["pages"] = {}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert projection.active_documents() == {}


def test_complete_manifest_conflict_fails_closed(tmp_path) -> None:
    export_dir = tmp_path / "confluence"
    for name in ("one", "two"):
        path = export_dir / name / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"source_type": "confluence_cloud", "space_id": "kb",
                                    "status": "ok", "full_sync": True,
                                    "pages": {}}), encoding="utf-8")
    projection = WikiDocumentProjection(
        tmp_path / "documents", knowledge_base_id="kb", confluence_export_dir=export_dir,
    )
    with pytest.raises(ValueError, match="conflicting complete Confluence exports"):
        projection.active_documents()


def test_full_manifest_deletion_queues_durable_retraction(tmp_path) -> None:
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    export_dir = tmp_path / "confluence"
    space_dir = export_dir / "space"
    space_dir.mkdir(parents=True)
    document = _document(1)
    (documents_dir / f"{document.doc_id}.json").write_text(
        json.dumps(document.model_dump(mode="json")), encoding="utf-8",
    )
    store = WikiStore(tmp_path / "wiki.sqlite3")
    projection = WikiDocumentProjection(
        documents_dir, knowledge_base_id="kb", confluence_export_dir=export_dir,
    )
    lifecycle = WikiDocumentLifecycle(store, projection)
    assert len(lifecycle.reconcile()) == 1
    path = space_dir / "manifest.json"
    path.write_text(json.dumps({"source_type": "confluence_cloud", "space_id": "kb",
                                "status": "partial", "full_sync": True,
                                "pages": {}}), encoding="utf-8")
    assert lifecycle.reconcile() == []
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_source_tombstones").fetchone()[0] == 0
    path.write_text(json.dumps({"source_type": "confluence_cloud", "space_id": "kb",
                                "status": "ok", "full_sync": True,
                                "pages": {}}), encoding="utf-8")
    assert len(lifecycle.reconcile()) == 1
    with store.connection() as db:
        row = db.execute("SELECT op_type FROM wiki_pending_ops").fetchone()
        assert row["op_type"] == "DELETE"
        assert db.execute("SELECT document_id FROM wiki_source_tombstones").fetchone()[0] == document.doc_id
    jobs = lifecycle.coordinator.schedule(debounce_seconds=0)
    assert len(jobs) == 1
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_pending_ops").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM wiki_source_tombstones").fetchone()[0] == 1
    path.write_text(json.dumps({"source_type": "confluence_cloud", "space_id": "kb",
                                "status": "partial", "full_sync": True,
                                "pages": {"1": {}}}), encoding="utf-8")
    lifecycle.reconcile()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_source_tombstones").fetchone()[0] == 1
    assert lifecycle.load_for_lease({"source_scope": "enterprise", "owner_id": "",
                                     "knowledge_base_id": "kb"}) == []
    path.write_text(json.dumps({"source_type": "confluence_cloud", "space_id": "kb",
                                "status": "ok", "full_sync": True,
                                "pages": {"1": {}}}), encoding="utf-8")
    lifecycle.reconcile()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_source_tombstones").fetchone()[0] == 0
    assert len(lifecycle.load_for_lease({"source_scope": "enterprise", "owner_id": "",
                                         "knowledge_base_id": "kb"})) == 1


def test_reconcile_coalesces_updates_and_detects_document_deletion(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    first = document_to_wiki_source(_document(1), scope)
    second = document_to_wiki_source(_document(2), scope)

    class Projection:
        knowledge_base_id = "kb"
        documents = [first, second]

        def active_documents(self):
            return {"kb": list(self.documents)} if self.documents else {}

    projection = Projection()
    lifecycle = WikiDocumentLifecycle(store, projection)
    assert len(lifecycle.reconcile()) == 2
    assert lifecycle.reconcile() == []
    jobs = lifecycle.coordinator.schedule(debounce_seconds=0)
    assert len(jobs) == 1
    assert lifecycle.reconcile() == []  # a scheduled scope is rebuilt by one worker

    with store.connection() as db:
        db.execute(
            "INSERT INTO wiki_build_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("enterprise", "", "kb", "revision-built", "DRAFT", "a" * 64,
             "test-model", "test-prompt", 1, None),
        )
        db.executemany(
            "INSERT INTO wiki_build_documents VALUES(?,?,?,?,?,?,?)",
            [("enterprise", "", "kb", "revision-built", item.document_id,
              item.document_version_id, item.content_sha256) for item in (first, second)],
        )
        db.execute("UPDATE wiki_jobs SET status='COMPLETE' WHERE job_id=?", (jobs[0],))
    projection.documents = [first]
    assert len(lifecycle.reconcile()) == 1
    with store.connection() as db:
        row = db.execute("SELECT document_id,op_type FROM wiki_pending_ops").fetchone()
        assert row["document_id"] == second.document_id and row["op_type"] == "DELETE"
    assert lifecycle.reconcile() == []


def test_ingest_entrypoint_enqueues_after_authoritative_save(tmp_path, monkeypatch) -> None:
    from pipeline import auto_process

    doc = _document(1)
    saved = []
    monkeypatch.setattr(auto_process, "save_document", lambda doc_id, data: saved.append(doc_id))
    monkeypatch.setattr(auto_process, "embed_texts", lambda texts: [[1.0] for _ in texts])
    monkeypatch.setenv("WIKI_INGEST_ENABLED", "true")
    monkeypatch.setenv("ENTERPRISE_KNOWLEDGE_BASE_ID", "kb")
    monkeypatch.setenv("WIKI_DB_PATH", str(tmp_path / "wiki.sqlite3"))
    assert auto_process._index_document(
        doc, chunk_size=500, overlap=100, evidence_milvus=None, has_milvus=False,
    )
    assert saved == [doc.doc_id]
    with WikiStore(tmp_path / "wiki.sqlite3").connection() as db:
        row = db.execute("SELECT document_id,op_type FROM wiki_pending_ops").fetchone()
        assert row["document_id"] == doc.doc_id and row["op_type"] == "UPSERT"


def test_wiki_database_path_is_independent_of_service_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WIKI_DB_PATH", "data-persistence/data/wiki.sqlite3")
    assert resolve_wiki_db_path(tmp_path) == tmp_path / "data-persistence" / "data" / "wiki.sqlite3"
