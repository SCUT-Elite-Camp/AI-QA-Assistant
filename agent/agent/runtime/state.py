"""Private request results shared by the Fast and Thinking pipelines."""
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class StopReason(StrEnum):
    FINAL_ANSWER = "final_answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"
    NO_RELEVANT_CONTEXT = "no_relevant_context"
    POLICY_LIMIT = "policy_limit"
    MAX_ITERATIONS = "max_iterations"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    QUALITY_VALIDATION_FAILED = "quality_validation_failed"


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iteration: int
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    error_code: str = ""


class AgentRunResult(BaseModel):
    stop_reason: StopReason
    answer: str = ""
    message: str = ""
    iterations: int = 0
    retrieval_attempts: int = 0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str = ""
    llm_metrics: dict[str, Any] = Field(default_factory=dict)
    answer_grounding: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
