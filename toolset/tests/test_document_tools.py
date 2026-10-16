import json

import pytest

from tool_layer.document_tools import (
    DocumentRepository,
    FindDocumentsTool,
    GetDocumentTool,
)


class FakeBM25:
    def search(self, query, top_k, filters):
        if query == "benefits":
            return [
                {
                    "doc_id": "hr-policy",
                    "text": "employee benefits policy",
                    "score": 2.0,
                }
            ]
        return []


class FakeSearchTool:
    def __init__(self, documents_dir):
        self.documents_dir = documents_dir
        self.bm25_index = FakeBM25()


def _write_document(path, doc_id, *, title, space="HR", doc_type="md", chunks=None):
    value = {
        "doc_id": doc_id,
        "title": title,
        "space": space,
        "doc_type": doc_type,
        "last_updated": "2026-09-23T00:00:00Z",
        "source_url": f"https://example.test/{doc_id}",
        "chunks": chunks or [],
    }
    (path / f"{doc_id}.json").write_text(json.dumps(value), encoding="utf-8")


def test_repository_rejects_path_traversal(tmp_path):
    repository = DocumentRepository(tmp_path)

    with pytest.raises(ValueError, match="invalid_doc_id"):
        repository.load("../secret")


def test_find_documents_combines_metadata_and_content_matches(tmp_path):
    _write_document(tmp_path, "hr-policy", title="HR Handbook")
    _write_document(tmp_path, "finance-policy", title="Finance Rules", space="Finance")
    tool = FindDocumentsTool(FakeSearchTool(tmp_path))

    result = tool.execute(query="benefits", filters={"space": "HR"}, top_k=5)

    assert result["result_count"] == 1
    assert result["documents"][0]["doc_id"] == "hr-policy"
    assert result["documents"][0]["match_summary"] == "employee benefits policy"


def test_find_documents_preserves_empty_allowlist(tmp_path):
    _write_document(tmp_path, "hr-policy", title="HR Handbook")
    tool = FindDocumentsTool(FakeSearchTool(tmp_path))

    assert tool.execute(filters={"doc_ids": []}) == {
        "documents": [],
        "result_count": 0, "total_documents": 0, "has_more": False, "next_offset": None,
    }


@pytest.mark.parametrize("query", [None, 1, True, ["benefits"]])
def test_find_documents_rejects_non_string_query_values(tmp_path, query):
    tool = FindDocumentsTool(FakeSearchTool(tmp_path))

    with pytest.raises(ValueError, match="query must be a string"):
        tool.execute(query=query, filters={"space": "HR"})


def test_find_documents_schema_matches_query_length_limit(tmp_path):
    query_schema = FindDocumentsTool(FakeSearchTool(tmp_path)).parameters["properties"]["query"]

    assert query_schema["maxLength"] == 512


def test_find_documents_rejects_oversized_query_before_search(tmp_path):
    class CountingBM25:
        def __init__(self):
            self.calls = []

        def search(self, query, top_k, filters):
            self.calls.append((query, top_k, filters))
            return []

    search = FakeSearchTool(tmp_path)
    search.bm25_index = CountingBM25()
    tool = FindDocumentsTool(search)

    with pytest.raises(ValueError, match="512 characters"):
        tool.execute(query="x" * 513)

    assert search.bm25_index.calls == []


def test_find_documents_rejects_internal_chunk_filter_before_search(tmp_path):
    class CountingBM25:
        def __init__(self):
            self.calls = []

        def search(self, query, top_k, filters):
            self.calls.append((query, top_k, filters))
            return []

    search = FakeSearchTool(tmp_path)
    search.bm25_index = CountingBM25()
    tool = FindDocumentsTool(search)

    with pytest.raises(ValueError, match="unsupported filter keys: chunk_ids"):
        tool.execute(query="benefits", filters={"chunk_ids": ["chunk-1"]})

    assert search.bm25_index.calls == []


@pytest.mark.parametrize(
    "filters",
    [
        {"doc_id": ["hr-policy"]},
        {"doc_id": ("hr-policy",)},
        {"doc_id": {"hr-policy"}},
        {"doc_ids": "hr-policy"},
        {"doc_ids": ("hr-policy",)},
        {"doc_ids": {"hr-policy"}},
    ],
)
def test_find_documents_rejects_filter_shapes_outside_schema_before_search(
    tmp_path, filters
):
    class CountingBM25:
        def __init__(self):
            self.calls = []

        def search(self, query, top_k, filters):
            self.calls.append((query, top_k, filters))
            return []

    search = FakeSearchTool(tmp_path)
    search.bm25_index = CountingBM25()

    with pytest.raises(ValueError):
        FindDocumentsTool(search).execute(query="benefits", filters=filters)

    assert search.bm25_index.calls == []


def test_find_documents_preserves_filter_alias_intersection(tmp_path):
    class CountingBM25:
        def __init__(self):
            self.calls = []

        def search(self, query, top_k, filters):
            self.calls.append((query, top_k, filters))
            return []

    search = FakeSearchTool(tmp_path)
    search.bm25_index = CountingBM25()

    FindDocumentsTool(search).execute(
        query="benefits",
        filters={"doc_id": " hr-policy ", "doc_ids": ["hr-policy", "finance-policy"]},
    )

    assert search.bm25_index.calls[0][2] == {"doc_ids": ["hr-policy"]}


def test_find_documents_preserves_omitted_query_and_top_k_boundaries(tmp_path):
    class CountingBM25:
        def __init__(self):
            self.calls = []

        def search(self, query, top_k, filters):
            self.calls.append((query, top_k, filters))
            return []

    search = FakeSearchTool(tmp_path)
    search.bm25_index = CountingBM25()
    tool = FindDocumentsTool(search)
    _write_document(tmp_path, "hr-policy", title="HR Handbook")

    assert tool.execute(filters={"space": "HR"})["documents"][0]["doc_id"] == "hr-policy"
    tool.execute(query="benefits", top_k=1)
    tool.execute(query="benefits", top_k=20)

    assert [call[1] for call in search.bm25_index.calls] == [50, 200]


@pytest.mark.parametrize("top_k", [True, False, 0, 21])
def test_find_documents_rejects_boolean_and_out_of_range_top_k(tmp_path, top_k):
    tool = FindDocumentsTool(FakeSearchTool(tmp_path))

    with pytest.raises(ValueError, match="top_k must be an integer"):
        tool.execute(query="benefits", top_k=top_k)


def test_get_document_reads_multiple_complete_documents(tmp_path):
    _write_document(tmp_path, "first", title="First", chunks=[
        {"index": i, "text": f"chunk-{i}"} for i in reversed(range(151))])
    _write_document(tmp_path, "second", title="Second", chunks=[{"index": 0, "text": "Other document"}])
    result = GetDocumentTool(tmp_path).execute(doc_ids=["first", "second", "first"])
    assert [doc["doc_id"] for doc in result["documents"]] == ["first", "second"]
    first = result["documents"][0]
    assert len(first["chunks"]) == 151
    assert first["chunks"][0]["text"] == "chunk-0"
    assert first["content"].endswith("chunk-150")
    assert all(chunk["evidence_ref"] for chunk in first["chunks"])
    assert result["errors"] == []


def test_get_document_prefers_full_parsed_content(tmp_path):
    document = {"doc_id": "full", "title": "Full", "content": "Heading and full body",
                "chunks": [{"index": 0, "text": "body"}]}
    (tmp_path / "full.json").write_text(json.dumps(document), encoding="utf-8")
    assert GetDocumentTool(tmp_path).execute(doc_ids=["full"])["documents"][0]["content"] == document["content"]


def test_get_document_reads_document_without_chunks(tmp_path):
    (tmp_path / "full.json").write_text(json.dumps({"doc_id": "full", "content": "Full text"}), encoding="utf-8")
    doc = GetDocumentTool(tmp_path).execute(doc_ids=["full"])["documents"][0]
    assert doc["content"] == doc["chunks"][0]["text"] == "Full text"
    assert doc["chunks"][0]["evidence_ref"]


def test_get_document_reports_missing_documents_per_item(tmp_path):
    _write_document(tmp_path, "present", title="Present")
    result = GetDocumentTool(tmp_path).execute(doc_ids=["missing", "present"])
    assert result["errors"] == [{"error": "document_not_found", "doc_id": "missing"}]
    assert result["result_count"] == 1


@pytest.mark.parametrize("doc_ids", [None, [], "doc", ["doc"] * 21])
def test_get_document_rejects_invalid_batch(tmp_path, doc_ids):
    with pytest.raises(ValueError, match="doc_ids must contain"):
        GetDocumentTool(tmp_path).execute(doc_ids=doc_ids)


@pytest.mark.parametrize("doc_id", ["", "../secret", "has space", "x" * 129, None, True])
def test_get_document_validates_entire_batch_before_loading(tmp_path, doc_id):
    tool = GetDocumentTool(tmp_path)
    tool.repository.load = lambda *_: pytest.fail("invalid batch must not read any document")
    with pytest.raises(ValueError, match="invalid_doc_id"):
        tool.execute(doc_ids=["valid", doc_id])


def test_find_documents_lists_authorized_catalog_with_pagination(tmp_path):
    for doc_id in ("a", "b", "c", "hidden"):
        _write_document(tmp_path, doc_id, title=doc_id)
    tool = FindDocumentsTool(FakeSearchTool(tmp_path))
    first = tool.execute(filters={"doc_ids": ["a", "b", "c"]}, top_k=2)
    assert [doc["doc_id"] for doc in first["documents"]] == ["a", "b"]
    assert first["total_documents"] == 3
    second = tool.execute(filters={"doc_ids": ["a", "b", "c"]}, top_k=2, offset=first["next_offset"])
    assert [doc["doc_id"] for doc in second["documents"]] == ["c"]
    assert second["next_offset"] is None
    assert not second["has_more"]
    assert tool.execute()["total_documents"] == 4


@pytest.mark.parametrize("offset", [True, -1, "0"])
def test_find_documents_validates_offset(tmp_path, offset):
    with pytest.raises(ValueError, match="offset"):
        FindDocumentsTool(FakeSearchTool(tmp_path)).execute(offset=offset)
