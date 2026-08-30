"""Local Deep Research control plane and runtime building blocks."""

from .claims import ClaimGenerator, generate_claims
from .coverage import CoverageEngine, compute_coverage
from .dispatcher import DurableDispatcher
from .execution import ResearchRuntimeService
from .manifest import (
    InMemoryDocumentResolver,
    LocalDocumentResolver,
    ManifestResolutionError,
)
from .planner import MockResearchPlanner, PlannerError
from .pipeline import ManifestScopedWorkerTools, ResearchIntelligencePipeline
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
from .evidence import EvidenceLedger
from .runtime import ResearchGraphRuntime
from .structural_verifier import StructuralVerifier
from .tools import LocalResearchToolAdapter
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
    "ManifestScopedWorkerTools",
    "LocalResearchWorker",
    "ManifestResolutionError",
    "MockResearchPlanner",
    "MockSemanticVerifier",
    "OriginalRead",
    "PlannerError",
    "ResearchConflictError",
    "ResearchControlPlane",
    "ResearchControlPlaneError",
    "ResearchIntelligencePipeline",
    "ResearchNotFoundError",
    "ResearchRuntimeService",
    "SQLiteResearchRepository",
    "EvidenceLedger",
    "LocalResearchToolAdapter",
    "ResearchGraphRuntime",
    "StructuralVerifier",
    "SearchHit",
    "compute_coverage",
    "generate_claims",
]
