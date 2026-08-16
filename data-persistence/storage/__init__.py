from storage.document_store import save_document, load_document, delete_document, list_documents


def __getattr__(name):
    if name == "MilvusStore":
        from storage.milvus_store import MilvusStore

        return MilvusStore
    raise AttributeError(name)


__all__ = [
    "save_document",
    "load_document",
    "delete_document",
    "list_documents",
    "MilvusStore",
]
from storage.chat_history_store import ChatHistoryStore
