from pydantic import BaseModel


class RewriteResult(BaseModel):
    """Structured result returned by the query rewriting stage."""

    original_query: str
    rewritten_query: str
    changed: bool
    reason: str = ""


class ClarificationDecision(BaseModel):
    """Decision made before query rewriting and retrieval."""

    needs_clarification: bool
    question: str = ""
    reason: str = ""
