from typing import Any, Literal, Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


MemoryFactCategory: TypeAlias = Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]


class _InternalMemoryContractModel(BaseModel):
    """Strict DTO base for trusted Web-to-Agent Memory requests only."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ChatRequest(BaseModel):
    # Public routes must reject, rather than silently ignore, internal-only fields.
    model_config = ConfigDict(extra="forbid")

    query: str
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict[str, Any]] = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"


class Citation(BaseModel):
    citation_id: int
    title: str
    source_url: Optional[str] = None
    doc_id: str
    chunk_id: str
    score: Optional[float] = None
    snippet: Optional[str] = None


class ChatResponse(BaseModel):
    trace_id: str
    status: str
    answer: str
    message: str
    citations: list[Citation]


class InternalActor(_InternalMemoryContractModel):
    user_id: str = Field(min_length=1)
    authenticated: Literal[True]


class MemoryMessage(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    revision: int = Field(gt=0)
    role: Literal["user", "assistant", "system"]
    content: str


class MemorySnapshotInput(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    version: int = Field(gt=0)
    revision: int = Field(gt=0)
    covered_to_sequence: int = Field(gt=0)
    summary: str


class MemoryFactInput(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    category: MemoryFactCategory
    value: str
    # Unix epoch milliseconds in UTC, or null when the Fact does not expire.
    expires_at: Optional[int] = Field(ge=0)


class MemoryContextInput(_InternalMemoryContractModel):
    actor: InternalActor
    chat_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    current_message_id: str = Field(min_length=1)
    current_sequence: int = Field(gt=0)
    snapshot: Optional[MemorySnapshotInput] = None
    facts: list[MemoryFactInput]
    tail: list[MemoryMessage]


class InternalChatRequest(ChatRequest):
    """Token-protected request envelope; never accepted by public /api/chat."""

    model_config = ConfigDict(extra="forbid", strict=True)

    memory_context: MemoryContextInput


class ContextArtifact(_InternalMemoryContractModel):
    memory_brief: str
    model_history: list[MemoryMessage]
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactProposal(_InternalMemoryContractModel):
    category: MemoryFactCategory
    value: str
    source_message_id: str = Field(min_length=1)
    expires_at: Optional[int] = Field(ge=0)


class MemoryRecall(_InternalMemoryContractModel):
    handled: bool
    answer: Optional[str] = None


class MemoryDecision(_InternalMemoryContractModel):
    context_artifact: Optional[ContextArtifact] = None
    fact_proposals: list[FactProposal] = Field(default_factory=list)
    recall: Optional[MemoryRecall] = None


class InternalChatResponse(_InternalMemoryContractModel):
    response: ChatResponse
    memory_decision: MemoryDecision


class CompactionPlanRequest(_InternalMemoryContractModel):
    actor: InternalActor
    chat_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    active_snapshot: Optional[MemorySnapshotInput]
    messages: list[MemoryMessage]
    tail_size: int = Field(gt=0)
    min_coverable_messages: int = Field(gt=0)
    soft_token_budget: int = Field(gt=0)


class ExpectedActiveSnapshot(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    version: int = Field(gt=0)
    revision: int = Field(gt=0)


class NewMemorySnapshot(_InternalMemoryContractModel):
    covered_from_sequence: int = Field(gt=0)
    covered_to_sequence: int = Field(gt=0)
    covered_from_message_id: str = Field(min_length=1)
    covered_to_message_id: str = Field(min_length=1)
    summary: str


class NoCompactionPlan(_InternalMemoryContractModel):
    should_compact: Literal[False]


class CompactionPlan(_InternalMemoryContractModel):
    should_compact: Literal[True]
    expected_active_snapshot: Optional[ExpectedActiveSnapshot]
    new_snapshot: NewMemorySnapshot


CompactionPlanResponse: TypeAlias = NoCompactionPlan | CompactionPlan


class ResetShortWindowRequest(_InternalMemoryContractModel):
    chat_id: str = Field(min_length=1)


class ResetShortWindowResponse(_InternalMemoryContractModel):
    status: Literal["ok"]
