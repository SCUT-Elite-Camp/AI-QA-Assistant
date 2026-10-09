from typing import Any, Literal, Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


MemoryFactCategory: TypeAlias = Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]


class _InternalMemoryContractModel(BaseModel):
    """Strict DTO base for trusted Web-to-Agent Memory requests only."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SourceDependency(_InternalMemoryContractModel):
    """Every source introduced into model context, not only cited sources."""

    source_type: Literal["knowledge", "attachment", "personal"] = "knowledge"
    doc_id: str = Field(min_length=1, max_length=200)
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    version: Optional[int | str] = None
    content_hash: Optional[str] = None


class EvidenceProvenance(_InternalMemoryContractModel):
    schema_version: Literal["evidence.provenance.v1"] = "evidence.provenance.v1"
    complete: bool
    dependencies: list[SourceDependency] = Field(default_factory=list)
    trace_id: str


class ChatRequest(BaseModel):
    # Public routes must reject, rather than silently ignore, internal-only fields.
    model_config = ConfigDict(extra="forbid")

    query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict[str, Any]] = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    exploration_mode: Literal["auto", "off", "force"] = "auto"
    topic_id: Optional[str] = None
    weight_mode: Optional[Literal["thinking", "auto", "fast", "deeper", "wider"]] = "thinking"
    soul_content: Optional[str] = None
    topic_doc_ids: Optional[list[str]] = None
    topic_titles: Optional[list[str]] = None
    consecutive_no_new_docs_count: int = 0
    is_first_message: Optional[bool] = None
    knowledge_base_retrieval_enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def reject_public_memory_context(cls, value: Any) -> Any:
        """Keep browser-supplied persistent Memory out of the public route."""
        trusted_fields = {
            "memory_context",
            "personal_library_context",
            "attachment_context",
        }
        if (
            cls is ChatRequest
            and isinstance(value, dict)
            and trusted_fields.intersection(value)
        ):
            raise ValueError("trusted context memory_context/personal_library_context/attachment_context is only accepted by the internal endpoint")
        return value


class Citation(BaseModel):
    citation_id: int
    title: str
    source_url: Optional[str] = None
    doc_id: str
    chunk_id: str
    score: Optional[float] = None
    snippet: Optional[str] = None
    source_type: Literal["knowledge", "attachment", "personal"] = "knowledge"
    attachment_id: Optional[str] = None
    evidence_id: Optional[str] = None
    locator: Optional[dict[str, Any]] = None
    version: Optional[int | str] = None
    source_scope: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    evidence_ref: Optional[str] = None
    content_hash: Optional[str] = None
    normalized_content_hash: Optional[str] = None
    source_content_hash: Optional[str] = None
    source_version: Optional[int | str] = None
    read_status: Optional[str] = None


class ChatResponse(BaseModel):
    trace_id: str
    status: str
    answer: str
    message: str
    citations: list[Citation]
    chat_title: Optional[str] = None
    evidence_provenance: Optional[EvidenceProvenance] = None
    diagnostics: Optional[dict[str, Any]] = None


class InternalActor(_InternalMemoryContractModel):
    user_id: str = Field(min_length=1)
    authenticated: Literal[True]


class MemoryMessage(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    revision: int = Field(gt=0)
    role: Literal["user", "assistant", "system"]
    content: str
    source_dependencies: list[SourceDependency] = Field(default_factory=list)
    provenance_complete: bool = False


class MemorySnapshotInput(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    version: int = Field(gt=0)
    revision: int = Field(gt=0)
    covered_to_sequence: int = Field(gt=0)
    summary: str
    source_dependencies: list[SourceDependency] = Field(default_factory=list)
    provenance_complete: bool = False


class MemoryFactInput(_InternalMemoryContractModel):
    id: str = Field(min_length=1)
    category: MemoryFactCategory
    value: str
    # Unix epoch milliseconds in UTC, or null when the Fact does not expire.
    expires_at: Optional[int] = Field(ge=0)
    source_dependencies: list[SourceDependency] = Field(default_factory=list)
    provenance_complete: bool = False


class MemoryContextInput(_InternalMemoryContractModel):
    actor: InternalActor
    chat_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    current_message_id: str = Field(min_length=1)
    current_sequence: int = Field(gt=0)
    snapshot: Optional[MemorySnapshotInput] = None
    facts: list[MemoryFactInput]
    tail: list[MemoryMessage]
    source_dependencies: list[SourceDependency] = Field(default_factory=list)
    provenance_complete: bool = False


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



class PersonalLibraryContext(BaseModel):
    """Server-authenticated library scope; never accepted by the public route."""

    model_config = ConfigDict(extra="forbid")

    owner_user_id: str = Field(min_length=1, max_length=200)
    knowledge_base_id: str = Field(min_length=1, max_length=200)
    access_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttachmentContext(BaseModel):
    """Server-authorized attachment IDs for this request."""

    model_config = ConfigDict(extra="forbid")

    allowed_attachment_ids: list[str] = Field(default_factory=list, max_length=100)
    selected_attachment_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_selection(self) -> "AttachmentContext":
        allowed = set(self.allowed_attachment_ids)
        if any(not value.startswith("att_") for value in allowed):
            raise ValueError("allowed attachment IDs must use the att_ prefix")
        if any(value not in allowed for value in self.selected_attachment_ids):
            raise ValueError("selected attachments must be included in the allowlist")
        self.allowed_attachment_ids = list(dict.fromkeys(self.allowed_attachment_ids))
        self.selected_attachment_ids = list(dict.fromkeys(self.selected_attachment_ids))
        return self


class InternalChatRequest(ChatRequest):
    """Token-protected request envelope; never accepted by public /api/chat."""

    model_config = ConfigDict(extra="forbid", strict=True)

    memory_context: MemoryContextInput
    personal_library_context: PersonalLibraryContext | None = None
    attachment_context: AttachmentContext | None = None


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
    # Deprecated internal BFF compatibility fields.  Agent settings are the
    # sole authority for compaction thresholds; callers may omit these fields.
    tail_size: Optional[int] = Field(default=None, gt=0)
    min_coverable_messages: Optional[int] = Field(default=None, gt=0)
    soft_token_budget: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _reject_explicit_null_legacy_thresholds(self) -> "CompactionPlanRequest":
        """Allow omitted legacy fields, but never accept an explicit null value."""

        for field_name in (
            "tail_size",
            "min_coverable_messages",
            "soft_token_budget",
        ):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} must be a positive integer when provided")
        return self


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
    source_dependencies: list[SourceDependency] = Field(default_factory=list)
    provenance_complete: bool = False


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
