"""Pure normalized inputs for versioned persistent-memory resolution.

These types only normalize an already validated internal DTO.  They do not
read storage, call a model, or add a persistence dependency.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.chat import MemoryContextInput, MemoryFactInput, MemoryMessage, MemorySnapshotInput


class PersistentSnapshot(BaseModel):
    """A versioned history checkpoint supplied by the trusted BFF."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    version: int = Field(gt=0)
    revision: int = Field(gt=0)
    covered_to_sequence: int = Field(gt=0)
    summary: str
    status: Literal["ACTIVE", "ARCHIVED", "EXPIRED"] = "ACTIVE"

    @classmethod
    def from_input(cls, snapshot: MemorySnapshotInput) -> "PersistentSnapshot":
        return cls(
            id=snapshot.id,
            version=snapshot.version,
            revision=snapshot.revision,
            covered_to_sequence=snapshot.covered_to_sequence,
            summary=snapshot.summary,
        )


class PersistentFact(BaseModel):
    """A normalized fact whose lifecycle is filtered deterministically."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    category: Literal["GOAL", "PREFERENCE", "PLAN_CONSTRAINT"]
    value: str
    status: Literal["PROPOSED", "CONFIRMED", "REVOKED"] = "CONFIRMED"
    scope: Literal["SESSION", "USER"] = "SESSION"
    expires_at: int | None = Field(default=None, ge=0)

    @classmethod
    def from_input(cls, fact: MemoryFactInput) -> "PersistentFact":
        return cls(
            id=fact.id,
            category=fact.category,
            value=fact.value,
            expires_at=fact.expires_at,
        )


class PersistentMemoryContext(BaseModel):
    """Trusted BFF context with only resolver-local lifecycle metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)

    current_message_id: str = Field(min_length=1)
    current_sequence: int = Field(gt=0)
    revision: int = Field(gt=0)
    snapshot: PersistentSnapshot | None = None
    facts: list[PersistentFact] = Field(default_factory=list)
    tail: list[MemoryMessage] = Field(default_factory=list)
    actor_authenticated: bool = True

    @classmethod
    def from_input(cls, context: MemoryContextInput) -> "PersistentMemoryContext":
        return cls(
            current_message_id=context.current_message_id,
            current_sequence=context.current_sequence,
            revision=context.revision,
            snapshot=(
                PersistentSnapshot.from_input(context.snapshot)
                if context.snapshot is not None
                else None
            ),
            facts=[PersistentFact.from_input(fact) for fact in context.facts],
            tail=list(context.tail),
            actor_authenticated=context.actor.authenticated,
        )
