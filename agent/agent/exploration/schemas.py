from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExplorationAction(StrEnum):
    WIKI_SEARCH = "wiki_search"
    WIKI_READ_PAGE = "wiki_read_page"
    WIKI_READ_SOURCES = "wiki_read_sources"
    WIKI_SEARCH_EVIDENCE = "wiki_search_evidence"


class CoverageAssessment(BaseModel):
    """Structured decision made after authoritative Direct Evidence retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    complex_query: bool
    sufficient: bool
    should_explore: bool
    covered_facets: list[str] = Field(default_factory=list)
    missing_facets: list[str] = Field(default_factory=list)
    recommended_actions: list[ExplorationAction] = Field(default_factory=list)
    unique_documents: int = Field(ge=0)
    unique_sections: int = Field(ge=0)
    unique_evidence: int = Field(ge=0)
    reason: str
