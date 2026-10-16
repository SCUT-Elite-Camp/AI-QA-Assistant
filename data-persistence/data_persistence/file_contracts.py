"""Validated server-side private file contracts shared by HTTP and local tools."""
import os
from pydantic import BaseModel, Field

class EvidenceCorrection(BaseModel):
    expected_version: int = Field(ge=1)
    corrected_content: str = Field(min_length=1, max_length=200_000)
    reason: str = Field(default="", max_length=500)
    actor_id: str = Field(min_length=1, max_length=128)


_QUERY_VECTOR_DIM = int(os.getenv("LOCAL_EMBEDDING_MODEL_DIM", "1024"))
if not 1 <= _QUERY_VECTOR_DIM <= 65536:
    raise ValueError("invalid_embedding_dimension")


class SearchRequest(BaseModel):
    attachment_ids: list[str] = Field(max_length=100)
    query: str = Field(default="", max_length=4000)
    top_k: int = Field(default=10, ge=1, le=50)
    query_vector: list[float] | None = Field(default=None, min_length=_QUERY_VECTOR_DIM, max_length=_QUERY_VECTOR_DIM)


class LibrarySearchRequest(BaseModel):
    owner_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_ids: list[str] | None = Field(default=None, max_length=100)
    mode: str = Field(default="hybrid", pattern="^(hybrid|vector|bm25)$")
    query_vector: list[float] | None = Field(default=None, min_length=_QUERY_VECTOR_DIM, max_length=_QUERY_VECTOR_DIM)


class ScopeUpdate(BaseModel):
    scope: str
    chat_id: str | None = Field(default=None, max_length=256)
    topic_id: str | None = Field(default=None, max_length=256)
    expires_at: int | None = None
    dedupe_domain: str | None = Field(default=None, min_length=1, max_length=256)


class LibraryActivation(BaseModel):
    version_number: int = Field(ge=1)
    explicit: bool = False
