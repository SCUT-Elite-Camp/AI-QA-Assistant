"""Normalized, in-process models for trusted persistent Memory input.

These models are deliberately separate from the Web-to-Agent transport DTOs.
The BFF remains responsible for loading and authorizing persistent records;
the Agent only normalizes that trusted input before building a prompt artifact.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.chat import MemoryContextInput, MemoryFactInput, MemoryMessage, MemorySnapshotInput


class PersistentSnapshot(BaseModel):
    """A Snapshot normalized for defensive resolution inside the Agent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    revision: int = Field(ge=1)
    covered_to_sequence: int = Field(ge=1)
    summary: str
    status: Literal["ACTIVE", "ARCHIVED", "EXPIRED"] = "ACTIVE"

    @classmethod
    def from_input(cls, snapshot: MemorySnapshotInput) -> "PersistentSnapshot":
        """Normalize the contract DTO as an active Snapshot from the BFF."""
        return cls(
            id=snapshot.id,
            version=snapshot.version,
            revision=snapshot.revision,
            covered_to_sequence=snapshot.covered_to_sequence,
            summary=snapshot.summary,
        )


class PersistentFact(BaseModel):
    """A Fact with lifecycle fields used by the pure resolver filter."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]
    value: str
    expires_at: int | None = Field(default=None, ge=0)
    status: Literal["PROPOSED", "CONFIRMED", "REVOKED"] = "CONFIRMED"
    scope: Literal["SESSION", "USER"] = "SESSION"

    @classmethod
    def from_input(cls, fact: MemoryFactInput) -> "PersistentFact":
        """The internal DTO already contains BFF-filtered confirmed SESSION Facts."""
        return cls(
            id=fact.id,
            category=fact.category,
            value=fact.value,
            expires_at=fact.expires_at,
        )


class PersistentMemoryContext(BaseModel):
    """Trusted context consumed by :class:`ContextResolver` only."""

    model_config = ConfigDict(extra="forbid")

    actor_authenticated: bool
    chat_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    current_message_id: str = Field(min_length=1)
    current_sequence: int = Field(ge=1)
    snapshot: PersistentSnapshot | None = None
    facts: list[PersistentFact] = Field(default_factory=list)
    tail: list[MemoryMessage] = Field(default_factory=list)

    @classmethod
    def from_input(cls, context: MemoryContextInput) -> "PersistentMemoryContext":
        """Convert the frozen transport contract without adding persistence access."""
        return cls(
            actor_authenticated=context.actor.authenticated,
            chat_id=context.chat_id,
            revision=context.revision,
            current_message_id=context.current_message_id,
            current_sequence=context.current_sequence,
            snapshot=(
                PersistentSnapshot.from_input(context.snapshot)
                if context.snapshot is not None
                else None
            ),
            facts=[PersistentFact.from_input(fact) for fact in context.facts],
            tail=list(context.tail),
        )
