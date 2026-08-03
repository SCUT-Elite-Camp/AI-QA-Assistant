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

    # A-MEM agentic 检索扩展字段
    source_type: Optional[str] = None   # "card" / "segment" / None(legacy)
    keywords: Optional[list[str]] = None
    tags: Optional[list[str]] = None
