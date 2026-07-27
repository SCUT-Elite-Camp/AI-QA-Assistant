from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.schemas.query_plan import QueryIntent, QueryPlan


class IntentResult(BaseModel):
    """Internal structured result produced by IntentClassifier."""

    model_config = ConfigDict(extra="forbid")

    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    is_follow_up: bool = False
    is_clarification_reply: bool = False
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


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
