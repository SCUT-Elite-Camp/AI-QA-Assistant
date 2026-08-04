"""Structured, request-local results returned by ToolExecutor."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    chunk_id: str
    chunk_index: int = Field(default=0, ge=0)
    title: str
    content: str
    source_url: str = ""
    score: float = Field(ge=0.0, le=1.0)

    retrieval_query: str
    retrieval_mode: str
    retrieval_attempt: int = Field(default=1, ge=1, le=2)

    @field_validator(
        "doc_id",
        "chunk_id",
        "title",
        "content",
        "retrieval_query",
        "retrieval_mode",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required evidence text must not be empty")
        return normalized


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    success: bool

    data: dict[str, Any] | None = None
    evidence: list[Evidence] = Field(default_factory=list)

    error_code: str = ""
    error_message: str = ""
    elapsed_ms: int = Field(default=0, ge=0)

    @field_validator("tool_call_id", "tool_name")
    @classmethod
    def require_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool identity must not be empty")
        return normalized

    @field_validator("error_code", "error_message")
    @classmethod
    def normalize_error_text(cls, value: str) -> str:
        return value.strip()
