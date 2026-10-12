import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "data-persistence", ROOT / "toolset"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from scripts.check_milvus_provenance import check_milvus_provenance  # noqa: E402


class FakeCollection:
    num_entities = 4

    def __init__(self):
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return [
            {
                "chunk_id": "structured",
                "page_number": 0,
                "bbox_json": "",
                "metadata_json": (
                    '{"page_regions":[{"page_number":2,"bbox":[1,2,3,4],'
                    '"block_ids":["b1"],"sources":["native"],"confidence":1.0}]}'
                ),
            },
            {
                "chunk_id": "legacy",
                "page_number": 3,
                "bbox_json": "[1,2,3,4]",
                "metadata_json": '{"source":"native"}',
            },
            {
                "chunk_id": "malformed",
                "page_number": 4,
                "bbox_json": "[2,3,4,5]",
                "metadata_json": "not-json",
            },
            {
                "chunk_id": "missing",
                "page_number": 0,
                "bbox_json": "",
                "metadata_json": "{}",
            },
        ]


class FakeStore:
    def __init__(self, collection=None, error=None):
        self.collection = collection
        self.error = error
        self.validated = []

    def connect(self):
        if self.error is not None:
            raise self.error

    def get_existing_collection(self, collection_name):
        return self.collection

    def validate_chunk_schema(self, collection_name):
        self.validated.append(collection_name)


def test_live_check_reports_structured_legacy_malformed_and_missing_rows():
    collection = FakeCollection()
    store = FakeStore(collection)

    report = check_milvus_provenance(store=store, collection_name="doc_chunks", sample_limit=10)

    assert report == {
        "status": "ok",
        "collection": "doc_chunks",
        "entities": 4,
        "sampled": 4,
        "structured_region_rows": 1,
        "legacy_fallback_rows": 2,
        "missing_region_rows": 1,
        "malformed_metadata_rows": 1,
    }
    assert store.validated == ["doc_chunks"]
    assert collection.query_calls == [{
        "expr": "id >= 0",
        "output_fields": ["chunk_id", "page_number", "bbox_json", "metadata_json"],
        "limit": 10,
    }]


def test_live_check_reports_unavailable_service_without_mutation():
    store = FakeStore(error=RuntimeError("connection refused"))

    report = check_milvus_provenance(store=store)

    assert report["status"] == "error"
    assert "connection refused" in report["error"]
    assert store.validated == []


def test_live_check_reports_missing_collection():
    report = check_milvus_provenance(store=FakeStore(collection=None))

    assert report == {
        "status": "error",
        "collection": "doc_chunks",
        "error": "collection not found",
    }
