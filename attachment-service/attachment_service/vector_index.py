from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class AttachmentVectorIndex:
    """Optional independent Milvus collection for attachment evidence."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false").lower() in {"1", "true", "yes"}
        self.collection = os.getenv("ATTACHMENT_MILVUS_COLLECTION", "attachment_evidence_cp2")
        knowledge_collection = os.getenv("MILVUS_COLLECTION", "doc_chunks_cp2_bgem3")
        if self.enabled and self.collection.strip().casefold() == knowledge_collection.strip().casefold():
            raise RuntimeError("attachment_milvus_collection_must_be_isolated")
        self._store = None
        self._retry_after = 0.0

    def _connect(self, store: Any) -> None:
        if time.monotonic() < self._retry_after:
            raise RuntimeError("attachment_vector_index_unavailable")
        try:
            store.connect()
        except Exception:
            self._retry_after = time.monotonic() + float(
                os.getenv("ATTACHMENT_VECTOR_RETRY_SECONDS", "30")
            )
            raise
        self._retry_after = 0.0

    def _dependencies(self):
        if not self.enabled:
            raise RuntimeError("attachment_vector_index_disabled")
        root = Path(__file__).resolve().parents[2]
        for path in (root / "data-pipeline", root / "data-persistence"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        from pipeline.embedder import embed_texts
        from storage.milvus_store import MilvusStore
        if self._store is None:
            self._store = MilvusStore(collection_name=self.collection)
        return embed_texts, self._store

    def replace(self, attachment_id: str, items: list[dict[str, Any]]) -> None:
        if os.name == "nt" and os.getenv("ATTACHMENT_VECTOR_CHILD") != "1":
            environment = os.environ.copy()
            environment["ATTACHMENT_VECTOR_CHILD"] = "1"
            completed = subprocess.run(
                [sys.executable, "-m", "attachment_service.vector_worker"],
                input=json.dumps({"attachment_id": attachment_id, "items": items}, ensure_ascii=False),
                text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=float(os.getenv("ATTACHMENT_VECTOR_PROCESS_TIMEOUT_SECONDS", "120")),
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("attachment_vector_index_unavailable")
            return
        self._replace_in_process(attachment_id, items)

    def _replace_in_process(self, attachment_id: str, items: list[dict[str, Any]]) -> None:
        embed_texts, store = self._dependencies()
        self._connect(store)
        store.init_collection(self.collection, dim=int(os.getenv("LOCAL_EMBEDDING_MODEL_DIM", "1024")))
        store.collection.delete(expr=f'doc_id == "{attachment_id}"')
        store.collection.flush()
        content_items = [item for item in items if str(item.get("content") or "").strip()]
        if not content_items:
            return
        embeddings = embed_texts([item["content"] for item in content_items])
        store.insert_chunks(
            embeddings=embeddings,
            chunk_ids=[item["evidence_id"] for item in content_items],
            chunk_texts=[item["content"] for item in content_items],
            doc_ids=[attachment_id] * len(content_items),
            chunk_indices=list(range(len(content_items))),
            source_urls=[f"/api/attachments/{attachment_id}/content"] * len(content_items),
            titles=[f"附件 {attachment_id}"] * len(content_items),
            spaces=["attachment"] * len(content_items),
            doc_types=["attachment"] * len(content_items),
            collection_name=self.collection,
        )

    def search_by_vector(
        self, attachment_ids: list[str], query_vector: list[float], top_k: int,
    ) -> list[dict[str, Any]]:
        _, store = self._dependencies()
        self._connect(store)
        try:
            hits = store.search_similar(query_vector, top_k=top_k, doc_ids_filter=attachment_ids, collection_name=self.collection)
        except Exception:
            self._retry_after = time.monotonic() + float(
                os.getenv("ATTACHMENT_VECTOR_RETRY_SECONDS", "30")
            )
            raise
        return [{"attachment_id": hit.entity.get("doc_id"), "evidence_id": hit.entity.get("chunk_id"), "content": hit.entity.get("chunk_text"), "score": float(hit.score)} for hit in hits]

    def delete(self, attachment_id: str) -> None:
        _, store = self._dependencies()
        self._connect(store)
        store.init_collection(self.collection, dim=int(os.getenv("LOCAL_EMBEDDING_MODEL_DIM", "1024")))
        store.collection.delete(expr=f'doc_id == "{attachment_id}"')
        store.collection.flush()
