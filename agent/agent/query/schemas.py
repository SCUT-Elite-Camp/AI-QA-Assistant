from typing import Any

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


class QueryEnrichment(BaseModel):
    """Internal sub-query and semantic-filter planning result."""

    model_config = ConfigDict(extra="forbid")

    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
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


class UnifiedQueryResult(BaseModel):
    """Internal one-call result for Query Understanding."""

    model_config = ConfigDict(extra="forbid")

    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    is_follow_up: bool = False
    is_clarification_reply: bool = False
    needs_clarification: bool = False
    clarification_question: str = ""
    ambiguity_reason: str = ""
    standalone_query: str
    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> Any:
        if isinstance(value, str):
            named = {"high": 0.9, "medium": 0.6, "low": 0.3}
            return named.get(value.strip().lower(), value)
        return value

    @field_validator("clarification_question", "ambiguity_reason", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        return "" if value is None else value

    @field_validator("clarification_question", "ambiguity_reason", "standalone_query")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("sub_queries")
    @classmethod
    def normalize_unified_sub_queries(cls, values: list[str]) -> list[str]:
        return QueryEnrichment.normalize_sub_queries(values)


class QueryPreparationResult(BaseModel):
    """Internal combined rewrite and retrieval-planning result."""

    model_config = ConfigDict(extra="forbid")

    standalone_query: str
    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    @field_validator("filters", mode="before")
    @classmethod
    def normalize_empty_filters(cls, value: Any) -> Any:
        if value is None or value == []:
            return {}
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_optional_reason(cls, value: Any) -> Any:
        return "" if value is None else value

    @field_validator("standalone_query", "reason")
    @classmethod
    def strip_preparation_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("sub_queries")
    @classmethod
    def normalize_preparation_sub_queries(cls, values: list[str]) -> list[str]:
        return QueryEnrichment.normalize_sub_queries(values)
