"""Composition root for the Deep Research Core Vertical Slice."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.schemas.research import ClaimVerificationStatus

from .dispatcher import DurableDispatcher
from .manifest import LocalDocumentResolver
from .pipeline import ResearchIntelligencePipeline
from .planner import ResearchPlanner
from .repository import SQLiteResearchRepository
from .runtime import ResearchGraphRuntime
from .service import ApprovedResearchContext, ResearchControlPlane
from .tools import LocalJsonSearchBackend, LocalResearchToolAdapter
from .verifier import MockSemanticVerifier, SemanticVerifier
from .worker import ResearchLedger


class ResearchRuntimeService:
    """Own the dispatcher, Graph and adapters for one Repository."""

    def __init__(
        self,
        control_plane: ResearchControlPlane,
        tool_adapter: LocalResearchToolAdapter,
        checkpointer: BaseCheckpointSaver,
        *,
        semantic_verifier: SemanticVerifier | None = None,
        ledger: ResearchLedger | None = None,
        stage_hook: Callable[[str, str], None] | None = None,
        checkpoint_connection: sqlite3.Connection | None = None,
        owns_repository: bool = False,
    ) -> None:
        self.control_plane = control_plane
        self.tool_adapter = tool_adapter
        self.checkpoint_connection = checkpoint_connection
        self.owns_repository = owns_repository
        self.pipeline = ResearchIntelligencePipeline(
            control_plane,
            tool_adapter,
            semantic_verifier=semantic_verifier,
            ledger=ledger,
        )
        self.runtime = ResearchGraphRuntime(
            control_plane,
            self.pipeline,
            checkpointer,
            stage_hook=stage_hook,
        )
        self.dispatcher = DurableDispatcher(
            control_plane,
            executor=self._execute,
            recovery_executor=self.runtime.resume,
        )

    @classmethod
    def from_local_catalog(
        cls,
        *,
        database_path: str | Path,
        documents_dir: str | Path,
        checkpoint_path: str | Path | None = None,
        id_factory=None,
        planner: ResearchPlanner | None = None,
        semantic_statuses: dict[str, ClaimVerificationStatus | str] | None = None,
        ledger: ResearchLedger | None = None,
        stage_hook: Callable[[str, str], None] | None = None,
    ) -> "ResearchRuntimeService":
        """Build a durable, network-free runtime over fixed local documents."""

        database_path = Path(database_path)
        documents_dir = Path(documents_dir)
        checkpoint_path = Path(checkpoint_path or database_path.with_suffix(".graph.db"))
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        repository = SQLiteResearchRepository(database_path)
        control_plane = ResearchControlPlane(
            repository,
            source_resolver=LocalDocumentResolver(documents_dir),
            planner=planner,
            id_factory=id_factory,
        )
        adapter = LocalResearchToolAdapter(
            LocalJsonSearchBackend(documents_dir),
            documents_dir,
        )
        checkpoint_connection = sqlite3.connect(
            str(checkpoint_path),
            check_same_thread=False,
        )
        checkpointer = SqliteSaver(checkpoint_connection)
        verifier = (
            MockSemanticVerifier(semantic_statuses)
            if semantic_statuses is not None
            else None
        )
        return cls(
            control_plane,
            adapter,
            checkpointer,
            semantic_verifier=verifier,
            ledger=ledger,
            stage_hook=stage_hook,
            checkpoint_connection=checkpoint_connection,
            owns_repository=True,
        )

    def _execute(self, context: ApprovedResearchContext) -> None:
        self.runtime.run(context.job.research_id)

    def scan_once(self) -> list[str]:
        return self.dispatcher.scan_once()

    def close(self) -> None:
        self.tool_adapter.close()
        if self.checkpoint_connection is not None:
            self.checkpoint_connection.close()
        if self.owns_repository:
            self.control_plane.repository.close()


__all__ = ["ResearchRuntimeService"]
