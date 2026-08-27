"""Local Deep Research control plane and runtime building blocks."""

from .claims import ClaimGenerator, generate_claims
from .coverage import CoverageEngine, compute_coverage
from .dispatcher import DurableDispatcher
from .manifest import (
    InMemoryDocumentResolver,
    LocalDocumentResolver,
    ManifestResolutionError,
)
from .planner import MockResearchPlanner, PlannerError
from .repository import (
    ResearchConflictError,
    ResearchNotFoundError,
    SQLiteResearchRepository,
)
from .service import (
    ApprovedResearchContext,
    ResearchControlPlane,
    ResearchControlPlaneError,
)
from .verifier import DeterministicSemanticVerifier, MockSemanticVerifier
from .worker import (
    ConservativeCriterionMapper,
    InMemoryResearchLedger,
    LocalResearchWorker,
    OriginalRead,
    SearchHit,
)

__all__ = [
    "ApprovedResearchContext",
    "ClaimGenerator",
    "ConservativeCriterionMapper",
    "CoverageEngine",
    "DeterministicSemanticVerifier",
    "DurableDispatcher",
    "InMemoryDocumentResolver",
    "InMemoryResearchLedger",
    "LocalDocumentResolver",
    "LocalResearchWorker",
    "ManifestResolutionError",
    "MockResearchPlanner",
    "MockSemanticVerifier",
    "OriginalRead",
    "PlannerError",
    "ResearchConflictError",
    "ResearchControlPlane",
    "ResearchControlPlaneError",
    "ResearchNotFoundError",
    "SQLiteResearchRepository",
    "SearchHit",
    "compute_coverage",
    "generate_claims",
]
