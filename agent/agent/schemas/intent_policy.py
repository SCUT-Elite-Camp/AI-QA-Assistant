"""Deterministic execution policy selected from a frozen QueryIntent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_tools: tuple[str, ...] = ()

    retrieval_strategy: Literal["none", "vector", "bm25", "hybrid"] = "hybrid"
    evidence_policy: Literal[
        "none",
        "single_fact",
        "document_identity",
        "topic_coverage",
        "bilateral_coverage",
    ] = "single_fact"
    assembly_strategy: Literal[
        "none",
        "score_order",
        "document_order",
        "group_by_target",
    ] = "score_order"
    answer_style: Literal[
        "concise_qa",
        "document_list",
        "structured_summary",
        "comparison_table",
        "direct_chat",
        "capability_help",
        "unsupported",
    ] = "concise_qa"

    top_k: int = Field(default=5, ge=0, le=20)
    max_iterations: int = Field(default=3, ge=0, le=10)
    max_tool_calls: int = Field(default=2, ge=0, le=10)
    max_retrieval_attempts: int = Field(default=2, ge=0, le=2)

    requires_citations: bool = True
