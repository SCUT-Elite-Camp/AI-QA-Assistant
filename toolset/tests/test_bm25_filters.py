import json

import pytest

from retrieval.bm25_index import BM25Index


def _write_document(path, doc_id, *, space, doc_type, text):
    (path / f"{doc_id}.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "title": doc_id,
                "space": space,
                "doc_type": doc_type,
                "chunks": [
                    {
                        "chunk_id": f"{doc_id}::chunk_0",
                        "index": 0,
                        "text": text,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_bm25_applies_filters_before_top_k(tmp_path):
    _write_document(tmp_path, "doc-finance", space="Finance", doc_type="pdf", text="shared policy")
    _write_document(tmp_path, "doc-hr", space="HR", doc_type="md", text="shared policy")

    index = BM25Index()
    index.build_from_documents(str(tmp_path))

    results = index.search("shared policy", top_k=1, filters={"space": "HR"})

    assert [row["doc_id"] for row in results] == ["doc-hr"]


def test_bm25_empty_allowlist_returns_no_results(tmp_path):
    _write_document(tmp_path, "doc-1", space="HR", doc_type="pdf", text="shared policy")
    index = BM25Index()
    index.build_from_documents(str(tmp_path))

    assert index.search("shared policy", filters={"doc_ids": []}) == []


def test_bm25_requires_rebuild_for_legacy_metadata_filters(tmp_path):
    _write_document(tmp_path, "doc-1", space="HR", doc_type="pdf", text="shared policy")
    index = BM25Index()
    index.build_from_documents(str(tmp_path))
    index._chunk_meta[0].pop("space")

    with pytest.raises(RuntimeError, match="rebuild the BM25 index"):
        index.search("shared policy", filters={"space": "HR"})
