from retrieval.bm25_index import BM25Index


def test_document_scope_is_applied_before_top_k_ranking():
    index = BM25Index()
    index._chunk_meta = [
        {"doc_id": "other", "chunk_id": f"other-{i}", "text": "alpha"}
        for i in range(30)
    ] + [{"doc_id": "target", "chunk_id": "target-0", "text": "beta"}]
    index._tokenized_corpus = [index._analyzer.analyze(row["text"]) for row in index._chunk_meta]
    from rank_bm25 import BM25Okapi
    index._bm25 = BM25Okapi(index._tokenized_corpus)

    rows = index.search("alpha", top_k=5, filters={"doc_ids": ["target"]})

    assert [row["doc_id"] for row in rows] == ["target"]
