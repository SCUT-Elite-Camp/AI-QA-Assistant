"""Lazy compatibility exports for the legacy storage package.

New consumers should import persistence APIs from ``data_persistence`` domain
modules. These names remain available for older callers without importing any
storage backend until a specific export is requested.
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "save_document": ("storage.document_store", "save_document"),
    "load_document": ("storage.document_store", "load_document"),
    "delete_document": ("storage.document_store", "delete_document"),
    "list_documents": ("storage.document_store", "list_documents"),
    "ChatHistoryStore": ("storage.chat_history_store", "ChatHistoryStore"),
    "MilvusStore": ("storage.milvus_store", "MilvusStore"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load and cache a legacy export only when it is accessed."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
