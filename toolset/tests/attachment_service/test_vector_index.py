"""File destinations use the common vector backend and document worker."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_persistence.vector import get_file_vector_store
from pipeline.indexing.vectors import index_document_vectors
from pipeline.files.evidence import persisted_evidence_document


def test_file_vector_collection_is_independent_by_default(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.delenv("ATTACHMENT_MILVUS_COLLECTION", raising=False)
    monkeypatch.delenv("MILVUS_COLLECTION", raising=False)
    store = get_file_vector_store()
    from data_persistence.vector import MilvusStore
    assert isinstance(store, MilvusStore)
    assert store.collection_name == "attachment_evidence_cp2"


@pytest.mark.parametrize("protected", ["MILVUS_COLLECTION", "SECTION_MILVUS_COLLECTION"])
def test_file_vector_collection_rejects_enterprise_collision(monkeypatch, protected):
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.setenv("ATTACHMENT_MILVUS_COLLECTION", " Shared_Collection ")
    monkeypatch.setenv(protected, "shared_collection")
    with pytest.raises(RuntimeError, match="must_be_isolated"):
        get_file_vector_store()


def test_disabled_vector_index_does_not_construct_backend(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    monkeypatch.setattr("data_persistence.vector._vector_store_at", lambda *_: pytest.fail("backend constructed"))
    assert get_file_vector_store() is None


def test_search_uses_caller_vector_and_filters_before_common_backend(monkeypatch):
    from data_persistence.file_contracts import LibrarySearchRequest
    from tool_layer.search_library_tool import search_library_evidence

    calls = []
    class Store:
        def list_library_versions(self, owner, kb, **kwargs):
            calls.append((owner, kb, kwargs))
            return [{"id": "ver_owned", "vector_ref": "ver_owned__generation"}]
        def list_evidence(self, ids):
            assert ids == ["ver_owned"]
            return [{"attachment_id": "ver_owned", "evidence_id": "owned_chunk", "content": "owned"}]

    class Vector:
        collection_name = "isolated_personal"
        def search_similar(self, vector, **kwargs):
            calls.append((vector, kwargs))
            return [SimpleNamespace(entity={"doc_id": "ver_owned__generation", "chunk_id": "owned_chunk", "chunk_text": "owned"}, score=1.0)]

    monkeypatch.setattr("pipeline.indexing.embedder.embed_texts", lambda *_: pytest.fail("query re-embedded"))
    query = [0.0] * int(os.getenv("LOCAL_EMBEDDING_MODEL_DIM", "1024"))
    result = search_library_evidence(LibrarySearchRequest(
        owner_id="alice", knowledge_base_id="kb_alice", query="owned", mode="vector", query_vector=query,
    ), Store(), Vector())
    assert calls[0] == ("alice", "kb_alice", {"document_ids": None, "active_only": True})
    assert calls[1][0] == query
    assert calls[1][1]["doc_ids_filter"] == ["ver_owned__generation"]
    assert calls[1][1]["collection_name"] == "isolated_personal"
    assert result["items"][0]["attachment_id"] == "ver_owned"


def test_common_backend_short_circuits_failed_connections(monkeypatch):
    from data_persistence.vector import MilvusStore
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("milvus_down")
    monkeypatch.setattr("storage.milvus_store.connections.connect", fail)
    monkeypatch.setenv("MILVUS_CONNECT_RETRY_SECONDS", "30")
    store = MilvusStore(collection_name="isolated")
    with pytest.raises(RuntimeError, match="milvus_down"):
        store.connect()
    with pytest.raises(RuntimeError, match="vector_index_unavailable"):
        store.connect()
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows uses isolated vector workers")
def test_common_worker_receives_canonical_document_and_explicit_destination(monkeypatch):
    captured = {}
    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("pipeline.indexing.vectors.subprocess.run", run)
    document = persisted_evidence_document("ver_a__generation", [{"evidence_id": "chunk", "content": "text"}])
    backend = SimpleNamespace(collection_name="isolated", host="127.0.0.1", port="19539")
    index_document_vectors(document, backend)
    assert captured["command"][2] == "pipeline.indexing.worker"
    payload = json.loads(captured["input"])
    assert payload["collection"] == "isolated" and payload["port"] == "19539"
    assert payload["document"]["doc_id"] == "ver_a__generation"
    assert payload["document"]["chunks"][0]["text"] == "text"
    assert payload["document"]["source_url"] == "/api/attachments/ver_a/content"


@pytest.mark.skipif(os.name != "nt", reason="Windows uses isolated vector workers")
def test_common_worker_failure_is_reported(monkeypatch):
    monkeypatch.setattr("pipeline.indexing.vectors.subprocess.run", lambda *a, **k: SimpleNamespace(returncode=1))
    document = persisted_evidence_document("ver_a__generation", [{"evidence_id": "chunk", "content": "text"}])
    with pytest.raises(RuntimeError, match="vector_index_unavailable"):
        index_document_vectors(document, SimpleNamespace(collection_name="isolated", host="localhost", port="19530"))


def test_common_worker_protocol_in_spawned_interpreter():
    document = persisted_evidence_document("ver_a__generation", [{"evidence_id": "chunk", "content": "text"}])
    code = '''
import json
import runpy
import sys
from types import ModuleType

class Store:
    def __init__(self, **kwargs):
        assert kwargs == {"host": "127.0.0.1", "port": "19539", "collection_name": "isolated"}
        self.collection = self
    def connect(self): pass
    def init_collection(self, **kwargs): assert kwargs["dim"] == 2
    def validate_chunk_schema(self): pass
    def delete(self, expr): assert expr == 'doc_id == "ver_a__generation"'
    def flush(self): pass
    def insert_chunks(self, **rows):
        assert rows["doc_ids"] == ["ver_a__generation"]
        assert rows["chunk_texts"] == ["text"]
        assert rows["embeddings"] == [[1.0, 0.0]]
        assert rows["source_urls"] == ["/api/attachments/ver_a/content"]
        print("worker_protocol_passed")

vector = ModuleType("data_persistence.vector")
vector.MilvusStore = Store
sys.modules[vector.__name__] = vector
embedder = ModuleType("pipeline.indexing.embedder")
embedder.embed_texts = lambda texts: [[1.0, 0.0] for _ in texts]
sys.modules[embedder.__name__] = embedder
runpy.run_module("pipeline.indexing.worker", run_name="__main__")
'''
    result = subprocess.run(
        [sys.executable, "-c", code], input=json.dumps({
            "document": document.model_dump(mode="json"), "collection": "isolated",
            "host": "127.0.0.1", "port": "19539",
        }), cwd=Path(__file__).resolve().parents[3] / "data-pipeline",
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "worker_protocol_passed" in result.stdout
