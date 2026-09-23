"""Validation and matching for the public retrieval-filter contract."""

from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any


FILTER_KEYS = frozenset({"doc_id", "doc_ids", "space", "doc_type"})


def normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Validate filters and return one canonical, fail-closed representation.

    ``doc_id`` and ``doc_ids`` are aliases. When both are supplied, their
    intersection is used so a narrower caller constraint cannot widen an
    authorization allowlist. An explicitly empty allowlist remains empty.
    """
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be a dictionary")

    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise ValueError(f"unsupported filter keys: {', '.join(sorted(unknown))}")

    normalized: dict[str, Any] = {}
    doc_id_sets: list[list[str]] = []
    for key in ("doc_id", "doc_ids"):
        if key in filters:
            doc_id_sets.append(_normalize_doc_ids(filters[key], key))

    if doc_id_sets:
        selected = doc_id_sets[0]
        for candidates in doc_id_sets[1:]:
            allowed = set(candidates)
            selected = [value for value in selected if value in allowed]
        normalized["doc_ids"] = selected

    for key, max_length in (("space", 256), ("doc_type", 64)):
        if key not in filters:
            continue
        value = filters[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        candidate = value.strip()
        if key == "doc_type":
            candidate = _normalize_doc_type(candidate)
        if len(candidate) > max_length:
            raise ValueError(f"{key} must not exceed {max_length} characters")
        normalized[key] = candidate

    return normalized


def matches_filters(item: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    """Return whether a metadata row satisfies normalized retrieval filters."""
    normalized = normalize_filters(filters)
    if not normalized:
        return True

    if "doc_ids" in normalized:
        if str(item.get("doc_id", "")) not in normalized["doc_ids"]:
            return False
    if "space" in normalized and item.get("space") != normalized["space"]:
        return False
    if "doc_type" in normalized:
        actual = _normalize_doc_type(str(item.get("doc_type", "")))
        if actual != normalized["doc_type"]:
            return False
    return True


def build_milvus_filter_expression(filters: dict[str, Any] | None) -> str | None:
    """Serialize validated filters without accepting raw Milvus expressions."""
    normalized = normalize_filters(filters)
    clauses: list[str] = []
    if "doc_ids" in normalized:
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
    """Reject an existing collection built for another embedding dimension."""
    if int(actual) != int(expected):
        raise ValueError(
            f"Milvus embedding dimension mismatch: expected {expected}, got {actual}"
        )


def _normalize_doc_ids(value: Any, key: str) -> list[str]:
    if isinstance(value, str):
        values: Iterable[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        raise ValueError(f"{key} must be a string or a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("every doc_id must be a non-empty string")
        candidate = raw_value.strip()
        if len(candidate) > 128:
            raise ValueError("doc_id must not exceed 128 characters")
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    return normalized


def _normalize_doc_type(value: str) -> str:
    candidate = value.strip().lower()
    if "/" in candidate:
        candidate = candidate.rsplit("/", 1)[-1]
    return candidate.removeprefix(".")
