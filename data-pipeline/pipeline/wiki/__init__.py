"""Production contracts for evidence-grounded Wiki compilation."""

from .domain import (
    CandidateKind,
    EntityCategory,
    PromotionStatus,
    VerificationVerdict,
    WikiCandidate,
    WikiIdentity,
    WikiPageDraft,
    WikiScope,
    WikiSourceDocument,
)
from .source import document_to_wiki_source

__all__ = [
    "CandidateKind",
    "EntityCategory",
    "PromotionStatus",
    "VerificationVerdict",
    "WikiCandidate",
    "WikiIdentity",
    "WikiPageDraft",
    "WikiScope",
    "WikiSourceDocument",
    "document_to_wiki_source",
]
