from dataclasses import dataclass, field

import pytest

from storage.milvus_store import MilvusStore


@dataclass
class FakeField:
    name: str
    is_primary: bool = False
    auto_id: bool = False
    params: dict = field(default_factory=dict)


class FakeSchema:
    def __init__(self, names, *, dim=3):
        self.fields = [
            FakeField(
                name,
                is_primary=name == "id",
                auto_id=name == "id",
                params={"dim": dim} if name == "embedding" else {},
            )
            for name in names
        ]


class FakeCollection:
    def __init__(self, names):
        self.schema = FakeSchema(names)
        self.inserted = None
        self.search_kwargs = None
        self.flushed = False

    def insert(self, data):
        self.inserted = data
        return "insert-result"

    def flush(self):
        self.flushed = True

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return [[]]


def _store_with_collection(monkeypatch, collection):
    store = MilvusStore(collection_name="test_chunks")
    monkeypatch.setattr(store, "connect", lambda: None)

    def init_collection(collection_name=None, dim=384):
        store.collection = collection
        return collection

    monkeypatch.setattr(store, "init_collection", init_collection)
    return store


def test_insert_chunks_writes_metadata_for_new_schema(monkeypatch):
    fields = [
        "id",
        "embedding",
        "chunk_id",
        "chunk_text",
        "doc_id",
        "chunk_index",
        "source_url",
        "title",
        "space",
        "doc_type",
    ]
    collection = FakeCollection(fields)
    store = _store_with_collection(monkeypatch, collection)

    result = store.insert_chunks(
        embeddings=[[0.1, 0.2, 0.3]],
        chunk_ids=["chunk-1"],
        chunk_texts=["text"],
        doc_ids=["doc-1"],
        chunk_indices=[0],
        source_urls=["https://example.test"],
        titles=["Title"],
        spaces=["HR"],
        doc_types=["application/PDF"],
    )

    assert result == "insert-result"
    assert collection.inserted[-3:] == [["Title"], ["HR"], ["pdf"]]
    assert collection.flushed


def test_insert_chunks_remains_compatible_with_legacy_schema(monkeypatch):
    legacy_fields = [
        "id",
        "embedding",
        "chunk_id",
        "chunk_text",
        "doc_id",
        "chunk_index",
        "source_url",
    ]
    collection = FakeCollection(legacy_fields)
    store = _store_with_collection(monkeypatch, collection)

    store.insert_chunks(
        embeddings=[[0.1, 0.2, 0.3]],
        chunk_ids=["chunk-1"],
        chunk_texts=["text"],
        doc_ids=["doc-1"],
        chunk_indices=[0],
        titles=["ignored for legacy collection"],
    )

    assert len(collection.inserted) == 6


def test_search_pushes_supported_filters_to_milvus(monkeypatch):
    fields = [
        "id",
        "embedding",
        "chunk_id",
        "chunk_text",
        "doc_id",
        "chunk_index",
        "source_url",
        "title",
        "space",
        "doc_type",
    ]
    collection = FakeCollection(fields)
    store = _store_with_collection(monkeypatch, collection)

    assert store.search_similar(
        [0.1, 0.2, 0.3],
        filters={"doc_ids": ["doc-1"], "space": "HR", "doc_type": "pdf"},
    ) == []

    assert collection.search_kwargs["expr"] == (
        'doc_id in ["doc-1"] and space == "HR" and doc_type == "pdf"'
    )
    assert "space" in collection.search_kwargs["output_fields"]


def test_search_rejects_metadata_filter_on_legacy_schema(monkeypatch):
    collection = FakeCollection(
        ["id", "embedding", "chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url"]
    )
    store = _store_with_collection(monkeypatch, collection)

    with pytest.raises(ValueError, match="rebuild it with fields: space"):
        store.search_similar([0.1, 0.2, 0.3], filters={"space": "HR"})


def test_search_short_circuits_empty_allowlist(monkeypatch):
    collection = FakeCollection(
        ["id", "embedding", "chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url"]
    )
    store = _store_with_collection(monkeypatch, collection)

    assert store.search_similar([0.1, 0.2, 0.3], filters={"doc_ids": []}) == []
    assert collection.search_kwargs is None


def test_existing_collection_dimension_is_validated():
    collection = FakeCollection(["id", "embedding"])
    MilvusStore._validate_embedding_dimension(collection, 3)
    with pytest.raises(ValueError, match="expected 4, got 3"):
        MilvusStore._validate_embedding_dimension(collection, 4)
