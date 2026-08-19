from typing import Any, Optional

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    """Standard retrieval result used by the Agent Layer."""

    doc_id: str
    chunk_id: str
    chunk_index: int = 0
    chunk_text: str
    title: str
    source_url: Optional[str] = ""
    score: float = Field(ge=0.0, le=1.0)
    source_type: str = "knowledge"
    attachment_id: Optional[str] = None
    evidence_id: Optional[str] = None
    locator: Optional[dict[str, Any]] = None
    version: Optional[int] = None
    source_scope: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    version_id: Optional[str] = None
