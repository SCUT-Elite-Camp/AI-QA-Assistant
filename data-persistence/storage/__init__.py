from storage.document_store import save_document, load_document, delete_document, list_documents
from storage.chat_history_store import ChatHistoryStore


def __getattr__(name):
    """Load optional vector dependencies only when vector storage is requested."""
    if name == "MilvusStore":
        from storage.milvus_store import MilvusStore

        return MilvusStore
    raise AttributeError(name)


__all__ = [
    "save_document",
    "load_document",
    "delete_document",
    "list_documents",
    "ChatHistoryStore",
    "MilvusStore",
]
