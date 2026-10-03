"""Unified sparse/vector search for Wiki navigation candidates only."""

from __future__ import annotations

import array
import math
from typing import Any, Protocol


class WikiSearchProvider(Protocol):
    def search(
        self, query: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, top_k: int,
    ) -> list[dict[str, Any]]: ...


class SQLiteFTSWikiSearch:
    """Adapter over the revision- and scope-filtered WikiStore FTS query."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def search(
        self, query: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        return self.store.search_pages(
            query, source_scope=source_scope, owner_id=owner_id,
            knowledge_base_id=knowledge_base_id, top_k=top_k,
        )


class BgeM3Encoder:
    """Lazy, local BGE-M3 encoder for Wiki navigation text."""

    model_id = "BAAI/bge-m3"

    def __init__(self) -> None:
        self._model: Any | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_id, local_files_only=True)
            if self._model.get_sentence_embedding_dimension() != 1024:
                raise ValueError("BGE-M3 Wiki encoder must have 1024 dimensions")
        values = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [value.tolist() for value in values]


class BgeM3WikiVectorSearch:
    """Build and query a revision-scoped Wiki page vector index."""

    def __init__(self, store: Any, encoder: Any | None = None) -> None:
        self.store = store
        self.encoder = encoder or BgeM3Encoder()
        if self.encoder.model_id != BgeM3Encoder.model_id:
            raise ValueError("Wiki vector search requires BGE-M3")

    def index_active_revision(
        self, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    ) -> int:
        request = dict(source_scope=source_scope, owner_id=owner_id,
                       knowledge_base_id=knowledge_base_id)
        revision, pages = self.store.active_vector_pages(**request)
        if not revision:
            return 0
        return self._index_pages(request, revision, pages)

    def index_revision(
        self, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, revision: str,
    ) -> int:
        request = dict(source_scope=source_scope, owner_id=owner_id,
                       knowledge_base_id=knowledge_base_id)
        pages = self.store.revision_vector_pages(**request, revision=revision)
        return self._index_pages(request, revision, pages)

    def _index_pages(
        self, request: dict[str, str], revision: str, pages: list[dict[str, str]],
    ) -> int:
        values = self.encoder.embed([page["text"] for page in pages])
        if len(values) != len(pages):
            raise ValueError("BGE-M3 Wiki embedding count mismatch")
        vectors = [(page["page_id"], _vector_bytes(value))
                   for page, value in zip(pages, values)]
        self.store.replace_page_vectors(**request, revision=revision,
                                        model_id=self.encoder.model_id, vectors=vectors)
        return len(vectors)

    def search(
        self, query: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        values = self.encoder.embed([query])
        if len(values) != 1:
            raise ValueError("BGE-M3 Wiki query embedding count mismatch")
        return self.store.search_page_vectors(
            source_scope=source_scope, owner_id=owner_id,
            knowledge_base_id=knowledge_base_id, model_id=self.encoder.model_id,
            query_vector=_vector_bytes(values[0]), top_k=top_k,
        )


def _vector_bytes(value: list[float]) -> bytes:
    if len(value) != 1024 or not all(math.isfinite(item) for item in value):
        raise ValueError("BGE-M3 Wiki vector must be finite and 1024-dimensional")
    norm = math.sqrt(sum(item * item for item in value))
    if norm <= 0:
        raise ValueError("BGE-M3 Wiki vector has zero norm")
    return array.array("f", (item / norm for item in value)).tobytes()


class WikiSearchBackend:
    """RRF fusion for Wiki navigation; returned pages are never citation authority."""

    def __init__(
        self, sparse: WikiSearchProvider, vector: WikiSearchProvider | None = None,
        *, rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("Wiki RRF k must be positive")
        self.sparse = sparse
        self.vector = vector
        self.rrf_k = rrf_k

    def search(
        self, query: str, *, source_scope: str, owner_id: str,
        knowledge_base_id: str, top_k: int = 8,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        top_k = min(20, max(1, int(top_k)))
        request = {
            "source_scope": source_scope, "owner_id": owner_id,
            "knowledge_base_id": knowledge_base_id, "top_k": max(top_k * 2, 10),
        }
        result_sets = [self.sparse.search(query, **request)]
        if self.vector is not None:
            result_sets.append(self.vector.search(query, **request))

        scores: dict[str, float] = {}
        pages: dict[str, dict[str, Any]] = {}
        for values in result_sets:
            seen: set[str] = set()
            for rank, value in enumerate(values, 1):
                page_id = str(value.get("page_id") or "")
                if not page_id or page_id in seen:
                    continue
                seen.add(page_id)
                scores[page_id] = scores.get(page_id, 0.0) + 1.0 / (self.rrf_k + rank)
                pages.setdefault(page_id, dict(value))
        ordered = sorted(scores, key=lambda page_id: (-scores[page_id], page_id))[:top_k]
        return [{
            **pages[page_id],
            "score": round(scores[page_id], 8),
            "citation_authority": False,
        } for page_id in ordered]
