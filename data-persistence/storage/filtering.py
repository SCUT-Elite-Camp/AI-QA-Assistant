"""Validation and backend serialization for supported retrieval filters."""

from __future__ import annotations

import json
from typing import Any


FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})


def normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and canonicalize the public retrieval filter contract."""
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be a dictionary")

    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise ValueError(f"unsupported filter keys: {', '.join(sorted(unknown))}")

    normalized: dict[str, Any] = {}
    raw_ids = filters.get("doc_ids")
    if raw_ids is None and filters.get("doc_id") is not None:
        raw_ids = [filters["doc_id"]]
    if raw_ids is not None:
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, (list, tuple, set)):
            raise ValueError("doc_ids must be a string or a list of strings")
        doc_ids: list[str] = []
        seen: set[str] = set()
        for value in raw_ids:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("every doc_id must be a non-empty string")
            candidate = value.strip()
            if len(candidate) > 128:
                raise ValueError("doc_id must not exceed 128 characters")
            if candidate not in seen:
                seen.add(candidate)
                doc_ids.append(candidate)
        if doc_ids:
            normalized["doc_ids"] = doc_ids

    for key, max_length in (("space", 256), ("doc_type", 64)):
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        candidate = value.strip()
        if key == "doc_type":
            candidate = candidate.lower().rsplit("/", 1)[-1].removeprefix(".")
        if len(candidate) > max_length:
            raise ValueError(f"{key} must not exceed {max_length} characters")
        normalized[key] = candidate
    return normalized


def matches_filters(item: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    """Match normalized filters against a chunk or document metadata row."""
    normalized = normalize_filters(filters)
    if not normalized:
        return True
    doc_ids = normalized.get("doc_ids")
    if doc_ids is not None and str(item.get("doc_id", "")) not in doc_ids:
        return False
    if "space" in normalized and item.get("space") != normalized["space"]:
        return False
    if "doc_type" in normalized:
        actual = str(item.get("doc_type", "")).removeprefix(".").lower()
        if actual != normalized["doc_type"]:
            return False
    return True


def build_milvus_filter_expression(filters: dict[str, Any] | None) -> str | None:
    """Serialize normalized filters without interpolating raw expression fragments."""
    normalized = normalize_filters(filters)
    clauses: list[str] = []
    if normalized.get("doc_ids"):
        values = ", ".join(
            json.dumps(value, ensure_ascii=False)
            for value in normalized["doc_ids"]
        )
        clauses.append(f"doc_id in [{values}]")
    for key in ("space", "doc_type"):
        if key in normalized:
            value = json.dumps(normalized[key], ensure_ascii=False)
            clauses.append(f"{key} == {value}")
    return " and ".join(clauses) or None


def validate_embedding_dimension(actual: int, expected: int) -> None:
    """Fail before search when an index was built with a different model dimension."""
    if int(actual) != int(expected):
        raise ValueError(
            f"Milvus embedding dimension mismatch: expected {expected}, got {actual}"
        )
