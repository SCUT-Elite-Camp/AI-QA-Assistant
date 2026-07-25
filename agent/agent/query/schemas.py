from pydantic import BaseModel


class RewriteResult(BaseModel):
    """Structured result returned by the query rewriting stage."""

    original_query: str
    rewritten_query: str
    changed: bool
    reason: str = ""
