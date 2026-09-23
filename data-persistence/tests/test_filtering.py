import pytest

from storage.filtering import matches_filters, normalize_filters


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
