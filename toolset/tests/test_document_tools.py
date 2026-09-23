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
