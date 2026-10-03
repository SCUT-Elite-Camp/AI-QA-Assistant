from __future__ import annotations

import json

from models.document import Document
from pipeline import auto_process
from pipeline.rag_lifecycle import (
    finish_retraction, mark_retraction_pending, pending_confluence_retractions,
    withdrawn_confluence_documents,
)
from retrieval.bm25_index import BM25Index


def _manifest(root, pages, *, status="ok", full_sync=True):
    space = root / "space"
    space.mkdir(parents=True, exist_ok=True)
    (space / "manifest.json").write_text(json.dumps({
        "source_type": "confluence_cloud", "space_id": "space-1",
        "status": status, "full_sync": full_sync,
        "pages": {page_id: {} for page_id in pages},
    }), encoding="utf-8")


def test_full_export_retracts_only_missing_page_and_excludes_its_bm25_chunks(tmp_path):
    exports, documents = tmp_path / "exports", tmp_path / "documents"
    documents.mkdir()
    _manifest(exports, ["page-2"])
    for document_id, page_id, text in (
        ("doc-1", "page-1", "obsolete unique phrase"),
        ("doc-2", "page-2", "active unique phrase"),
    ):
        (documents / f"{document_id}.json").write_text(json.dumps({
            "doc_id": document_id,
            "metadata": {"space_id": "space-1", "page_id": page_id},
            "chunks": [{"chunk_id": f"{document_id}-chunk", "index": 0, "text": text}],
        }), encoding="utf-8")

    pending = pending_confluence_retractions(documents, exports)
    assert [item.document_id for item in pending] == ["doc-1"]
    mark_retraction_pending(pending[0])
    withdrawn = json.loads(pending[0].path.read_text(encoding="utf-8"))
    assert withdrawn["active_version"] is False
    assert withdrawn["metadata"]["rag_retraction_pending"] is True
    index = BM25Index()
    index.build_from_documents(str(documents))
    assert index.document_count == 1
    assert {item["doc_id"] for item in index.search("unique phrase")} == {"doc-2"}
    finish_retraction(pending[0])
    assert pending_confluence_retractions(documents, exports) == []
    assert [item.document_id for item in withdrawn_confluence_documents(documents, exports)] == ["doc-1"]


def test_partial_export_cannot_retract_or_complete_pending_document(tmp_path):
    exports, documents = tmp_path / "exports", tmp_path / "documents"
    documents.mkdir()
    path = documents / "doc-1.json"
    path.write_text(json.dumps({
        "doc_id": "doc-1", "metadata": {"space_id": "space-1", "page_id": "page-1"},
        "chunks": [],
    }), encoding="utf-8")
    _manifest(exports, [], status="partial")
    assert pending_confluence_retractions(documents, exports) == []
    _manifest(exports, [], status="ok", full_sync=False)
    assert pending_confluence_retractions(documents, exports) == []
    _manifest(exports, [], status="ok", full_sync=True)
    pending = pending_confluence_retractions(documents, exports)
    assert len(pending) == 1
    mark_retraction_pending(pending[0])
    assert len(pending_confluence_retractions(documents, exports)) == 1


def test_stale_raw_file_cannot_reactivate_completed_tombstone(tmp_path, monkeypatch):
    raws = tmp_path / "raws"
    documents = tmp_path / "documents"
    documents.mkdir()
    raw = raws / "confluence" / "space" / "stale.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("old source", encoding="utf-8")
    _manifest(raws / "confluence", [], status="ok", full_sync=True)
    document_id = Document.generate_doc_id(str(raw.resolve()))
    (documents / f"{document_id}.json").write_text(json.dumps({
        "doc_id": document_id, "active_version": False,
        "metadata": {"space_id": "space-1", "page_id": "page-1"}, "chunks": [],
    }), encoding="utf-8")
    monkeypatch.setattr(auto_process, "RAWS_DIR", raws)
    monkeypatch.setattr(auto_process, "DOCS_DIR", documents)
    monkeypatch.setattr(auto_process, "_scan_folder", lambda _: [str(raw.resolve())])
    monkeypatch.setattr(auto_process, "get_new_or_modified_files", lambda _: (_ for _ in ()).throw(
        AssertionError("withdrawn raw document was submitted for reingestion")
    ))
    auto_process.auto_process_raws()
