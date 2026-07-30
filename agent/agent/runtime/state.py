from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.query_plan import QueryPlan


class StopReason(StrEnum):
    FINAL_ANSWER = "final_answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    NO_RELEVANT_CONTEXT = "no_relevant_context"
    MAX_ITERATIONS = "max_iterations"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    error_code: str = ""


class AgentState(BaseModel):
    """Request-scoped mutable state owned by one Agent Runner invocation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str
    query_plan: QueryPlan
    messages: list[dict[str, Any]] = Field(default_factory=list)
    iteration: int = 0
    retrieval_attempts: int = 0
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    stop_reason: StopReason | None = None


class AgentRunResult(BaseModel):
    """Structured Agent Runner output used by Chat orchestration and logs."""

    stop_reason: StopReason
    answer: str = ""
    message: str = ""
    iterations: int = 0
    retrieval_attempts: int = 0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str = ""
