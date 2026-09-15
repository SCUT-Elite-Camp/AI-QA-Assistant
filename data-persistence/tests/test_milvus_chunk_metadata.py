from types import SimpleNamespace

import pytest
from pymilvus import DataType

import storage.milvus_store as milvus_module
from storage.milvus_store import MilvusStore


class FakeCollection:
    def __init__(self, name, schema=None):
        self.name = name
        self.schema = schema
        self.indexes = []
        self.inserted_columns = None
        self.search_kwargs = None

    def create_index(self, field_name, params):
        self.indexes.append(SimpleNamespace(field_name=field_name))

    def load(self):
        pass

    def insert(self, columns):
        self.inserted_columns = columns
        return SimpleNamespace(insert_count=len(columns[0]))

    def flush(self):
        pass

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return [[]]


def valid_fields(dim=2):
    return [
        SimpleNamespace(name="embedding", dtype=DataType.FLOAT_VECTOR, params={"dim": dim}),
        SimpleNamespace(name="chunk_id", dtype=DataType.VARCHAR, params={"max_length": 256}),
        SimpleNamespace(name="chunk_text", dtype=DataType.VARCHAR, params={"max_length": 65535}),
        SimpleNamespace(name="doc_id", dtype=DataType.VARCHAR, params={"max_length": 128}),
        SimpleNamespace(name="chunk_index", dtype=DataType.INT32, params={}),
        SimpleNamespace(name="source_url", dtype=DataType.VARCHAR, params={"max_length": 512}),
        SimpleNamespace(name="space", dtype=DataType.VARCHAR, params={"max_length": 256}),
        SimpleNamespace(name="chunk_type", dtype=DataType.VARCHAR, params={"max_length": 64}),
        SimpleNamespace(name="block_id", dtype=DataType.VARCHAR, params={"max_length": 1024}),
        SimpleNamespace(name="table_id", dtype=DataType.VARCHAR, params={"max_length": 1024}),
        SimpleNamespace(name="page_number", dtype=DataType.INT64, params={}),
        SimpleNamespace(name="bbox_json", dtype=DataType.VARCHAR, params={"max_length": 256}),
        SimpleNamespace(name="metadata_json", dtype=DataType.VARCHAR, params={"max_length": 65535}),
    ]


@pytest.fixture
def fake_collection_factory(monkeypatch):
    collections = {}

    def factory(name, schema=None):
        if schema is not None:
            collections[name] = FakeCollection(name, schema)
        return collections[name]

    monkeypatch.setattr(milvus_module.connections, "connect", lambda *a, **kw: None)
    monkeypatch.setattr(milvus_module.utility, "has_collection", lambda name: name in collections)
    monkeypatch.setattr(milvus_module, "Collection", factory)
    return collections


def test_chunk_schema_contains_provenance_fields(fake_collection_factory):
    store = MilvusStore()

    collection = store.init_collection(dim=2)

    fields = {field.name: field for field in collection.schema.fields}
    assert {
        "chunk_type", "block_id", "table_id", "page_number", "bbox_json", "metadata_json",
    } <= fields.keys()
    assert fields["page_number"].dtype == DataType.INT64
    assert fields["metadata_json"].params["max_length"] >= 4096


def test_existing_collection_without_provenance_fails_with_migration_action(
    fake_collection_factory,
):
    old_fields = [
        SimpleNamespace(name="embedding", params={"dim": 2}),
        SimpleNamespace(name="chunk_id", params={}),
    ]
    fake_collection_factory["doc_chunks"] = FakeCollection(
        "doc_chunks", SimpleNamespace(fields=old_fields),
    )
    store = MilvusStore()

    with pytest.raises(ValueError) as error:
        store.init_collection(dim=2)

    message = str(error.value)
    assert "doc_chunks schema is missing PDF provenance fields" in message
    assert "bbox_json" in message and "metadata_json" in message
    assert "scripts/reindex.py" in message


@pytest.mark.parametrize(
    ("field_name", "dtype", "params"),
    [
        ("page_number", DataType.VARCHAR, {"max_length": 32}),
        ("metadata_json", DataType.VARCHAR, {"max_length": 1024}),
        ("chunk_text", DataType.VARCHAR, {"max_length": 4096}),
    ],
)
def test_existing_collection_with_unsafe_field_definition_requires_reindex(
    fake_collection_factory, field_name, dtype, params,
):
    fields = valid_fields()
    field_index = next(index for index, field in enumerate(fields) if field.name == field_name)
    fields[field_index] = SimpleNamespace(name=field_name, dtype=dtype, params=params)
    fake_collection_factory["doc_chunks"] = FakeCollection(
        "doc_chunks", SimpleNamespace(fields=fields),
    )

    with pytest.raises(ValueError) as error:
        MilvusStore().init_collection(dim=2)

    message = str(error.value)
    assert "doc_chunks schema is missing PDF provenance fields" in message
    assert field_name in message
    assert "scripts/reindex.py" in message


def test_insert_chunks_writes_metadata_columns(fake_collection_factory):
    store = MilvusStore()

    store.insert_chunks(
        embeddings=[[0.1, 0.2]],
        chunk_ids=["c1"],
        chunk_texts=["text"],
        doc_ids=["d1"],
        chunk_indices=[0],
        source_urls=[""],
        spaces=[""],
        chunk_types=["table_row"],
        block_ids=[""],
        table_ids=["t1"],
        page_numbers=[3],
        bbox_jsons=["[1,2,3,4]"],
        metadata_jsons=["{}"],
    )

    assert store.collection.inserted_columns[-6:] == [
        ["table_row"], [""], ["t1"], [3], ["[1,2,3,4]"], ["{}"],
    ]


def test_legacy_insert_call_gets_safe_provenance_defaults(fake_collection_factory):
    store = MilvusStore()

    store.insert_chunks(
        [[0.1, 0.2]], ["c1"], ["text"], ["d1"], [0], ["url"], ["space"],
        "legacy-positional-name",
    )

    assert store.collection.name == "legacy-positional-name"
    assert store.collection.inserted_columns[-6:] == [
        [""], [""], [""], [0], [""], [""],
    ]


def test_insert_rejects_any_column_length_mismatch(fake_collection_factory):
    store = MilvusStore()

    with pytest.raises(ValueError, match="metadata_jsons length 0 does not match embeddings length 1"):
        store.insert_chunks(
            embeddings=[[0.1, 0.2]], chunk_ids=["c1"], chunk_texts=["text"],
            doc_ids=["d1"], chunk_indices=[0], metadata_jsons=[],
        )


def test_insert_normalizes_explicit_none_provenance_values(fake_collection_factory):
    store = MilvusStore()

    store.insert_chunks(
        embeddings=[[0.1, 0.2]], chunk_ids=["c1"], chunk_texts=["text"],
        doc_ids=["d1"], chunk_indices=[0], chunk_types=[None], block_ids=[None],
        table_ids=[None], page_numbers=[None], bbox_jsons=[None], metadata_jsons=[None],
    )

    assert store.collection.inserted_columns[-6:] == [
        [""], [""], [""], [0], [""], [""],
    ]


def test_search_requests_provenance_fields(fake_collection_factory):
    store = MilvusStore()

    store.search_similar([0.1, 0.2])

    assert {
        "chunk_type", "block_id", "table_id", "page_number", "bbox_json", "metadata_json",
    } <= set(store.collection.search_kwargs["output_fields"])
