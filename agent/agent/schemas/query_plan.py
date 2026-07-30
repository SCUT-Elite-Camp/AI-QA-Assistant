"""Frozen public QueryPlan contract shared by CP2 Agent components."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QueryIntent(StrEnum):
    """Stable intent categories supported by the CP2 policy layer."""

    KNOWLEDGE_QA = "knowledge_qa"
    DOCUMENT_SEARCH = "document_search"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    CASUAL_CHAT = "casual_chat"
    SYSTEM_HELP = "system_help"
    UNSUPPORTED = "unsupported"


class QueryPlan(BaseModel):
    """Frozen output contract produced by Query Understanding."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    standalone_query: str

    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA
    intent_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    is_follow_up: bool = False
    is_clarification_reply: bool = False

    needs_clarification: bool = False
    clarification_question: str = ""
    ambiguity_reason: str = ""

    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("original_query")
    @classmethod
    def validate_original_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_query must not be empty")
        return value

    @field_validator("standalone_query")
    @classmethod
    def normalize_standalone_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("standalone_query must not be empty")
        return normalized

    @field_validator("clarification_question", "ambiguity_reason")
    @classmethod
    def strip_optional_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("sub_queries")
    @classmethod
    def normalize_sub_queries(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    @model_validator(mode="after")
    def validate_clarification(self) -> "QueryPlan":
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when needs_clarification is true"
            )
        if not self.needs_clarification:
            self.clarification_question = ""
        return self
