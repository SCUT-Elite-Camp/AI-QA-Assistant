from attachment_service.library_service import fuse_library_candidates


def _item(identifier: str):
    return {
        "evidence_id": identifier,
        "content": identifier,
        "locator": {},
    }


def test_hybrid_uses_more_candidates_than_top_k_and_calibrates_scores():
    evidence = {f"chunk-{index}": _item(f"chunk-{index}") for index in range(25)}
    lexical = [_item(f"chunk-{index}") for index in range(20)]
    vector = [_item(f"chunk-{index}") for index in range(10, 25)]

    items = fuse_library_candidates(evidence, lexical, vector, mode="hybrid", top_k=5)

    assert len(items) == 5
    assert all(0.0 <= item["score"] <= 1.0 for item in items)
    assert any(item["evidence_id"] in {f"chunk-{index}" for index in range(10, 20)} for item in items)


def test_bm25_and_vector_modes_do_not_mix_unrequested_backend():
    evidence = {"lexical": _item("lexical"), "vector": _item("vector")}
    lexical = [_item("lexical")]
    vector = [_item("vector")]
    assert [item["evidence_id"] for item in fuse_library_candidates(evidence, lexical, vector, mode="bm25", top_k=5)] == ["lexical"]
    assert [item["evidence_id"] for item in fuse_library_candidates(evidence, lexical, vector, mode="vector", top_k=5)] == ["vector"]
