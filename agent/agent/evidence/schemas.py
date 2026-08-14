from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.tool_execution import Evidence


class EvidenceGateResult(BaseModel):
    """Deterministic quality decision made before answer generation."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str
    covered_targets: list[str] = Field(default_factory=list)
    missing_targets: list[str] = Field(default_factory=list)
    candidate_evidence_count: int = Field(default=0, ge=0)
    eligible_evidence_count: int = Field(default=0, ge=0)
    rejected_evidence_count: int = Field(default=0, ge=0)
    should_retry: bool = False
    retrieval_attempt: int = Field(ge=1, le=2)
