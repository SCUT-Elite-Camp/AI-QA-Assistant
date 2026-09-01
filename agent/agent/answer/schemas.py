from pydantic import BaseModel, ConfigDict, Field


class AnswerCompletenessResult(BaseModel):
    """Structured answer-quality decision made after answer generation."""

    model_config = ConfigDict(extra="forbid")

    complete: bool
    missing_aspects: list[str] = Field(default_factory=list)
    missing_critical_facts: list[str] = Field(default_factory=list)
    reason: str = ""
    check_performed: bool = True
