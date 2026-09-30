"""Public document metadata persistence API."""

from pathlib import Path

from storage import document_store
from storage.document_store import (
    delete_document,
    list_documents,
    load_document,
    save_document,
)

__all__ = [
    "save_document",
    "load_document",
    "delete_document",
    "list_documents",
    "resolve_documents_dir",
]


def resolve_documents_dir() -> Path:
    """Return the configured document projection directory.

    Consumers that need filesystem access should use this resolver instead of
    depending on the storage implementation's module and path constant.
    """
    return Path(document_store.DOCS_DIR)
