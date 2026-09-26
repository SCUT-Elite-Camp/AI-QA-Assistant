import pytest

from storage.filtering import (
    build_milvus_filter_expression,
    matches_filters,
    normalize_filters,
    validate_embedding_dimension,
)


def test_normalize_filters_preserves_empty_allowlist():
    assert normalize_filters({"doc_ids": []}) == {"doc_ids": []}
    assert not matches_filters({"doc_id": "doc-1"}, {"doc_ids": []})


def test_normalize_filters_intersects_aliases():
    assert normalize_filters(
        {"doc_id": ["doc-1", "doc-2"], "doc_ids": ["doc-2", "doc-3"]}
    ) == {"doc_ids": ["doc-2"]}


def test_normalize_filters_validates_and_canonicalizes_values():
    assert normalize_filters(
        {
            "doc_ids": [" doc-1 ", "doc-1"],
            "space": " HR ",
            "doc_type": "application/PDF",
        }
    ) == {"doc_ids": ["doc-1"], "space": "HR", "doc_type": "pdf"}

    with pytest.raises(ValueError, match="unsupported filter keys"):
        normalize_filters({"tenant": "unsafe"})

    with pytest.raises(ValueError, match="every doc_id"):
        normalize_filters({"doc_ids": [""]})


def test_matches_filters_uses_canonical_doc_type():
    item = {"doc_id": "doc-1", "space": "HR", "doc_type": ".PDF"}
    assert matches_filters(item, {"doc_id": "doc-1", "space": "HR", "doc_type": "pdf"})
    assert not matches_filters(item, {"space": "Finance"})


def test_build_milvus_filter_expression_escapes_values():
    expression = build_milvus_filter_expression(
        {"doc_ids": ['doc-"1'], "space": "HR", "doc_type": ".PDF"}
    )

    assert expression == 'doc_id in ["doc-\\\"1"] and space == "HR" and doc_type == "pdf"'


def test_validate_embedding_dimension_rejects_mismatch():
    validate_embedding_dimension(384, 384)
    with pytest.raises(ValueError, match="expected 1024, got 384"):
        validate_embedding_dimension(384, 1024)
