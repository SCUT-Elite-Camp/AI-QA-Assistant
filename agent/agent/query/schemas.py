from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent


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


class QueryEnrichment(BaseModel):
    """Internal sub-query and semantic-filter planning result."""

    model_config = ConfigDict(extra="forbid")

    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    source_intent: SourceIntent = Field(default_factory=SourceIntent)
    reason: str = ""

    @field_validator("sub_queries")
    @classmethod
    def normalize_sub_queries(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("sub_queries must contain strings")
            query = value.strip()
            if query and query not in normalized:
                normalized.append(query)
        return normalized[:4]

    @field_validator("reason")
    @classmethod
    def strip_enrichment_reason(cls, value: str) -> str:
        return value.strip()
