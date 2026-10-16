"""File selection shares publication, failure and retraction behavior."""
import json
import os

import pytest

from pipeline.entrypoints.auto_process import auto_process_raws
from pipeline.entrypoints.process import process_folder
from pipeline.entrypoints.process_specific_files import process_specific_files
from pipeline.ingestion import batch, publication
from pipeline.confluence.lifecycle import Retraction
from storage import document_store


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    monkeypatch.setattr(document_store, "DOCS_DIR", str(documents))
    monkeypatch.setenv("BM25_INDEX_PATH", str(tmp_path / "bm25.pkl"))
    monkeypatch.setenv("MILVUS_COLLECTION", "isolated_evidence")
    monkeypatch.setenv("SECTION_MILVUS_COLLECTION", "isolated_sections")
    monkeypatch.setenv("WIKI_INGEST_ENABLED", "false")
    monkeypatch.setattr(batch.BM25Index, "default_index_path", staticmethod(
        lambda: pytest.fail("ingestion must use the selected runtime index path")))
    stores = []

    class Store:
        def __init__(self, **kwargs):
            self.collection_name = kwargs.get("collection_name", "isolated_evidence")
            self.collection = self
            self.writes, self.deletes = [], []
            stores.append(self)

        def connect(self): pass
        def init_collection(self, **kwargs): pass
        def validate_chunk_schema(self): pass
        def flush(self): pass
        def delete(self, expr): self.deletes.append(expr)
        def delete_document_chunks(self, doc_id): self.deletes.append(doc_id)
        def insert_chunks(self, **rows): self.writes.append(rows)

    monkeypatch.setattr(batch, "MilvusStore", Store)
    monkeypatch.setattr(publication, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    raws = tmp_path / "raws"
    raws.mkdir()
    source = raws / "notes.md"
    source.write_text("# Notes\nShared pipeline sentinel details.", encoding="utf-8")
    return source, documents, stores


@pytest.mark.parametrize("entry", ["folder", "explicit", "incremental"])
def test_all_entries_publish_same_vector_and_keyword_contract(runtime, entry):
    source, documents, stores = runtime
    if entry == "folder":
        process_folder(str(source.parent))
    elif entry == "explicit":
        process_specific_files([str(source)])
    else:
        auto_process_raws(raws_dir=source.parent, documents_dir=documents)
    [projection] = documents.glob("*.json")
    stored = json.loads(projection.read_text(encoding="utf-8"))
    assert stored["metadata"]["sync_status"] == "ready"
    assert stored["metadata"]["index_backends"] == ["bm25", "vector"]
    assert [store.collection_name for store in stores] == ["isolated_evidence", "isolated_sections"]
    assert stores[0].writes[0]["chunk_texts"] == [chunk["markdown_text"] for chunk in stored["chunks"]]
    index = batch.BM25Index()
    index.load(os.environ["BM25_INDEX_PATH"])
    assert {hit["doc_id"] for hit in index.search("sentinel")} == {stored["doc_id"]}


def test_unavailable_vectors_publish_partial_without_loading_model(runtime, monkeypatch):
    source, documents, _ = runtime
    monkeypatch.setattr(batch, "open_targets", lambda *a, **k: batch.IndexTargets(None, None, False))
    monkeypatch.setattr(publication, "embed_texts", lambda _: pytest.fail("offline ingestion loaded a model"))
    process_specific_files([str(source)])
    [projection] = documents.glob("*.json")
    metadata = json.loads(projection.read_text(encoding="utf-8"))["metadata"]
    assert metadata["sync_status"] == "partial" and metadata["index_backends"] == ["bm25"]


def test_collection_collision_is_not_treated_as_offline_fallback(runtime, monkeypatch):
    source, documents, stores = runtime
    monkeypatch.setenv("SECTION_MILVUS_COLLECTION", " ISOLATED_EVIDENCE ")
    with pytest.raises(RuntimeError, match="must differ"):
        process_specific_files([str(source)])
    assert not list(documents.glob("*.json"))
    assert not stores[0].deletes


def test_projection_directory_mismatch_is_rejected_before_backend_mutations(runtime):
    source, documents, stores = runtime
    with pytest.raises(ValueError, match="must match the configured persistence"):
        batch.run_batch([str(source)], documents_dir=documents.parent / "unbound")
    assert stores == []
    assert not list(documents.glob("*.json"))


def test_strict_parse_failure_does_not_publish_a_successful_generation(runtime, monkeypatch):
    source, documents, _ = runtime
    monkeypatch.setattr(batch, "parse_file", lambda _: (_ for _ in ()).throw(ValueError("bad source")))
    with pytest.raises(ValueError, match="bad source"):
        auto_process_raws(raws_dir=source.parent, documents_dir=documents, strict=True)
    assert not list(documents.glob("*.json"))
    assert not (source.parent.parent / "bm25.pkl").exists()


def test_keyword_failure_keeps_retraction_hidden_and_pending(runtime, monkeypatch):
    _, documents, stores = runtime
    documents.mkdir()
    projection = documents / "withdrawn.json"
    projection.write_text(json.dumps({"doc_id": "withdrawn", "metadata": {}}), encoding="utf-8")
    monkeypatch.setattr(batch, "refresh_keyword_index", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("keyword write failed")))
    with pytest.raises(RuntimeError, match="keyword write failed"):
        batch.run_batch([], documents_dir=documents, retractions=[Retraction("withdrawn", projection)])
    stored = json.loads(projection.read_text(encoding="utf-8"))
    assert stored["active_version"] is False
    assert stored["metadata"]["rag_retraction_pending"] is True
    assert all(store.deletes == ["withdrawn"] for store in stores)
