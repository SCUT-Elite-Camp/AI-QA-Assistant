from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.tool_execution import Evidence


class EvidenceGateResult(BaseModel):
    """Deterministic quality decision made before answer generation."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str
    missing_targets: list[str] = Field(default_factory=list)
    should_retry: bool = False
    retrieval_attempt: int = Field(ge=1, le=5)
