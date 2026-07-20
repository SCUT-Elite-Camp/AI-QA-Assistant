from typing import Optional

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
