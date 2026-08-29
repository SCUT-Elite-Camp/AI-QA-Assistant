"""Local Deep Research control plane and runtime building blocks."""

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
from .service import ApprovedResearchContext, ResearchControlPlane, ResearchControlPlaneError
from .evidence import EvidenceLedger
from .runtime import ResearchGraphRuntime
from .structural_verifier import StructuralVerifier
from .tools import LocalResearchToolAdapter

__all__ = [
    "ApprovedResearchContext",
    "DurableDispatcher",
    "InMemoryDocumentResolver",
    "LocalDocumentResolver",
    "ManifestResolutionError",
    "MockResearchPlanner",
    "PlannerError",
    "ResearchConflictError",
    "ResearchControlPlane",
    "ResearchControlPlaneError",
    "ResearchNotFoundError",
    "SQLiteResearchRepository",
    "EvidenceLedger",
    "LocalResearchToolAdapter",
    "ResearchGraphRuntime",
    "StructuralVerifier",
]

