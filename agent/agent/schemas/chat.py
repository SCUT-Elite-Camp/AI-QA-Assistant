from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict[str, Any]] = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"

    @model_validator(mode="before")
    @classmethod
    def reject_public_memory_context(cls, value: Any) -> Any:
        """Keep browser-supplied persistent Memory out of the public route."""
        if cls is ChatRequest and isinstance(value, dict) and "memory_context" in value:
            raise ValueError("memory_context is only accepted by the internal endpoint")
        return value


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
    chat_title: Optional[str] = None


class InternalActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    authenticated: Literal[True]


class MemoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    revision: int = Field(ge=1)
    role: Literal["user", "assistant", "system"]
    content: str


class MemorySnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    revision: int = Field(ge=1)
    covered_to_sequence: int = Field(ge=1)
    summary: str


class MemoryFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]
    value: str
    # Unix epoch milliseconds in UTC; null means that the Fact does not expire.
    expires_at: int | None = Field(default=None, ge=0)


class MemoryContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: InternalActor
    chat_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    current_message_id: str = Field(min_length=1)
    current_sequence: int = Field(ge=1)
    snapshot: MemorySnapshotInput | None = None
    facts: list[MemoryFactInput] = Field(default_factory=list)
    tail: list[MemoryMessage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sequence_alignment(self) -> "MemoryContextInput":
        if self.snapshot:
            if self.snapshot.revision != self.revision:
                raise ValueError("snapshot.revision must equal memory_context.revision")
            if self.snapshot.covered_to_sequence >= self.current_sequence:
                raise ValueError("snapshot.covered_to_sequence must precede current_sequence")

        previous_sequence = 0
        message_ids: set[str] = set()
        for message in self.tail:
            if message.revision != self.revision:
                raise ValueError("tail message revision must equal memory_context.revision")
            if message.sequence >= self.current_sequence:
                raise ValueError("tail message sequence must precede current_sequence")
            if self.snapshot and message.sequence <= self.snapshot.covered_to_sequence:
                raise ValueError(
                    "tail message sequence must follow snapshot.covered_to_sequence"
                )
            if message.sequence <= previous_sequence:
                raise ValueError("tail messages must be strictly ordered by sequence")
            if message.id == self.current_message_id or message.id in message_ids:
                raise ValueError("tail must not duplicate the current or another message ID")
            previous_sequence = message.sequence
            message_ids.add(message.id)

        return self


class InternalChatRequest(ChatRequest):
    """Contract-only request for the future token-protected internal endpoint."""

    model_config = ConfigDict(extra="forbid")

    memory_context: MemoryContextInput


class ContextArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_brief: str
    model_history: list[MemoryMessage]
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]
    value: str
    source_message_id: str = Field(min_length=1)
    expires_at: int | None = Field(default=None, ge=0)


class MemoryRecall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handled: bool
    answer: str | None = None


class MemoryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_artifact: ContextArtifact | None = None
    fact_proposals: list[FactProposal] = Field(default_factory=list)
    recall: MemoryRecall | None = None


class InternalChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: ChatResponse
    memory_decision: MemoryDecision = Field(default_factory=MemoryDecision)


class CompactionPlanRequest(BaseModel):
    """Trusted, already-persisted messages for deterministic Snapshot planning."""

    model_config = ConfigDict(extra="forbid")

    actor: InternalActor
    chat_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    active_snapshot: MemorySnapshotInput | None = None
    messages: list[MemoryMessage] = Field(default_factory=list)
    tail_size: int = Field(ge=1)
    min_coverable_messages: int = Field(ge=1)
    soft_token_budget: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_active_snapshot_revision(self) -> "CompactionPlanRequest":
        if self.active_snapshot and self.active_snapshot.revision != self.revision:
            raise ValueError("active_snapshot.revision must equal revision")
        previous_sequence = 0
        for message in self.messages:
            if message.revision != self.revision:
                raise ValueError("compaction message revision must equal revision")
            if message.sequence <= previous_sequence:
                raise ValueError("compaction messages must be strictly ordered by sequence")
            previous_sequence = message.sequence
        return self


class ExpectedActiveSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    revision: int = Field(ge=1)


class NewMemorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    covered_from_sequence: int = Field(ge=1)
    covered_to_sequence: int = Field(ge=1)
    covered_from_message_id: str = Field(min_length=1)
    covered_to_message_id: str = Field(min_length=1)
    summary: str

    @model_validator(mode="after")
    def validate_coverage(self) -> "NewMemorySnapshot":
        if self.covered_from_sequence > self.covered_to_sequence:
            raise ValueError("covered_from_sequence must not exceed covered_to_sequence")
        return self


class CompactionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_compact: bool
    expected_active_snapshot: ExpectedActiveSnapshot | None = None
    new_snapshot: NewMemorySnapshot | None = None

    @model_validator(mode="after")
    def validate_plan_shape(self) -> "CompactionPlanResponse":
        if self.should_compact != (self.new_snapshot is not None):
            raise ValueError("new_snapshot must exist exactly when should_compact is true")
        if not self.should_compact and self.expected_active_snapshot is not None:
            raise ValueError("expected_active_snapshot is only valid for a compaction plan")
        if (
            self.expected_active_snapshot is not None
            and self.new_snapshot is not None
            and self.expected_active_snapshot.revision < 1
        ):
            raise ValueError("expected_active_snapshot revision must be positive")
        return self


class ResetShortWindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(min_length=1)
