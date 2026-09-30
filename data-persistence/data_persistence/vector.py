"""Public vector persistence and retrieval-filter API."""

from typing import Any

from storage.filtering import (
    matches_filters,
    matches_normalized_filters,
    normalize_filters,
)

__all__ = [
    "MilvusStore",
    "matches_filters",
    "matches_normalized_filters",
    "normalize_filters",
]


def __getattr__(name: str) -> Any:
    if name != "MilvusStore":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from storage.milvus_store import MilvusStore

    globals()[name] = MilvusStore
    return MilvusStore


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
