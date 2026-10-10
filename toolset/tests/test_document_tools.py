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
        "result_count": 0,
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


def test_get_document_returns_ordered_pages(tmp_path):
    _write_document(
        tmp_path,
        "hr-policy",
        title="HR Handbook",
        chunks=[
            {"index": 2, "text": "third"},
            {"index": 0, "text": "first"},
            {"index": 1, "text": "second"},
        ],
    )
    tool = GetDocumentTool(tmp_path)

    first = tool.execute(doc_id="hr-policy", offset=0, limit=2)
    second = tool.execute(doc_id="hr-policy", offset=2, limit=2)

    assert [chunk["text"] for chunk in first["chunks"]] == ["first", "second"]
    assert first["has_more"] is True
    assert first["next_offset"] == 2
    assert [chunk["text"] for chunk in second["chunks"]] == ["third"]
    assert second["has_more"] is False
    assert second["next_offset"] is None


def test_get_document_reports_missing_document(tmp_path):
    assert GetDocumentTool(tmp_path).execute(doc_id="missing") == {
        "error": "document_not_found",
        "doc_id": "missing",
    }


def test_get_document_schema_matches_repository_id_constraints(tmp_path):
    schema = GetDocumentTool(tmp_path).parameters["properties"]["doc_id"]

    assert schema["minLength"] == 1
    assert schema["maxLength"] == 128
    assert schema["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


@pytest.mark.parametrize("doc_id", ["", "../secret", "has space", "x" * 129])
def test_get_document_rejects_malformed_document_ids(tmp_path, doc_id):
    with pytest.raises(ValueError, match="invalid_doc_id"):
        GetDocumentTool(tmp_path).execute(doc_id=doc_id)


@pytest.mark.parametrize("offset", [True, False, -1, 1.5, "0"])
def test_get_document_rejects_invalid_offsets(tmp_path, offset):
    with pytest.raises(ValueError, match="offset must be"):
        GetDocumentTool(tmp_path).execute(doc_id="hr-policy", offset=offset)


@pytest.mark.parametrize("limit", [True, False, 0, 51, 1.5, "1"])
def test_get_document_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError, match="limit must be"):
        GetDocumentTool(tmp_path).execute(doc_id="hr-policy", limit=limit)


def test_get_document_accepts_pagination_boundaries(tmp_path):
    _write_document(
        tmp_path,
        "hr-policy",
        title="HR Handbook",
        chunks=[{"index": index, "text": f"chunk-{index}"} for index in range(51)],
    )
    tool = GetDocumentTool(tmp_path)

    first = tool.execute(doc_id="hr-policy", offset=0, limit=1)
    last_page = tool.execute(doc_id="hr-policy", offset=1, limit=50)

    assert [chunk["text"] for chunk in first["chunks"]] == ["chunk-0"]
    assert first["has_more"] is True
    assert len(last_page["chunks"]) == 50
    assert last_page["has_more"] is False
