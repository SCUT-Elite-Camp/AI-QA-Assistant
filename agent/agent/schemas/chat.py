from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict[str, Any]] = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    topic_id: Optional[str] = None
    weight_mode: Optional[Literal["deeper", "auto", "wider"]] = "auto"
    topic_doc_ids: Optional[list[str]] = None
    topic_titles: Optional[list[str]] = None
    consecutive_no_new_docs_count: int = 0
    is_first_message: Optional[bool] = None


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
