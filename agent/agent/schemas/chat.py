from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AttachmentContext(BaseModel):
    selected_attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    topic_attachment_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_attachment_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def selected_must_be_allowed(self):
        allowed = set(self.allowed_attachment_ids)
        if not set(self.selected_attachment_ids).issubset(allowed):
            raise ValueError("selected attachments must be within request allowlist")
        if not set(self.topic_attachment_ids).issubset(allowed):
            raise ValueError("topic attachments must be within request allowlist")
        return self


class PersonalLibraryContext(BaseModel):
    owner_user_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    access_token: str = Field(min_length=64, max_length=64)


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict[str, Any]] = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    topic_id: Optional[str] = None
    weight_mode: Optional[Literal["deeper", "auto", "wider"]] = "auto"
    topic_doc_ids: Optional[list[str]] = None
    topic_titles: Optional[list[str]] = None
    consecutive_no_new_docs_count: int = 0
    is_first_message: Optional[bool] = None
    knowledge_base_retrieval_enabled: bool = True
    attachment_context: Optional[AttachmentContext] = None
    personal_library_context: Optional[PersonalLibraryContext] = None


class Citation(BaseModel):
    citation_id: int
    title: str
    source_url: Optional[str] = None
    doc_id: str
    chunk_id: str
    score: Optional[float] = None
    snippet: Optional[str] = None
    source_type: Literal["knowledge", "attachment", "personal"] = "knowledge"
    attachment_id: Optional[str] = None
    evidence_id: Optional[str] = None
    locator: Optional[dict[str, Any]] = None
    version: Optional[int] = None
    source_scope: Optional[Literal["personal", "enterprise", "attachment"]] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    version_id: Optional[str] = None


class ChatResponse(BaseModel):
    trace_id: str
    status: str
    answer: str
    message: str
    citations: list[Citation]
    chat_title: Optional[str] = None
