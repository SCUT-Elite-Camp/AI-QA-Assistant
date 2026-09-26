from __future__ import annotations

import json
from pathlib import Path

from retrieval.section_bm25_index import SectionBM25Index


def test_section_bm25_is_version_scoped_and_persistable(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    for doc_id, active, text in (
        ("doc-active", True, "Security Access Control least privilege ACL"),
        ("doc-other-1", True, "Cafeteria opening hours"),
        ("doc-other-2", True, "Holiday calendar"),
        ("doc-stale", False, "Security Access Control stale"),
    ):
        (documents / f"{doc_id}.json").write_text(json.dumps({
            "doc_id": doc_id, "active_version": active, "version_id": f"ver-{doc_id}",
            "space": "RAG", "doc_type": "md", "sections": [{
                "id": f"sec-{doc_id}", "navigation_text": text,
            }],
        }), encoding="utf-8")
    index = SectionBM25Index()
    index.build_from_documents(str(documents))
    path = tmp_path / "section.pkl"
    index.save(str(path))

    hits = SectionBM25Index.load(str(path)).search(
        "least privilege", top_k=5, filters={"doc_ids": ["doc-active"]},
    )

    assert [row["section_id"] for row in hits] == ["sec-doc-active"]
    assert all(row["doc_id"] != "doc-stale" for row in hits)
