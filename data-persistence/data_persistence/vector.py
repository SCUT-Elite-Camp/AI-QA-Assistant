"""Public vector persistence and retrieval-filter API."""

import os
from functools import lru_cache
from typing import Any

from storage.filtering import (
    matches_filters,
    matches_normalized_filters,
    normalize_filters,
)

__all__ = [
    "MilvusStore",
    "get_file_vector_store",
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


@lru_cache(maxsize=8)
def _vector_store_at(collection: str, host: str, port: str):
    from storage.milvus_store import MilvusStore
    return MilvusStore(host=host, port=port, collection_name=collection)


def get_file_vector_store():
    """Cache backend handles only; all source and owner checks remain request-local."""
    from data_persistence.file_settings import file_vector_collection

    collection = file_vector_collection()
    if collection is None:
        return None
    return _vector_store_at(collection, os.getenv("MILVUS_HOST", "localhost"), os.getenv("MILVUS_PORT", "19530"))
