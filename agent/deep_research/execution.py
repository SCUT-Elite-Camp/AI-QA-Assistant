"""Application composition of the single Deep Research coordinator harness."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.config.settings import settings
from .access import ResearchAccessPolicy
from .dispatcher import DurableDispatcher
from .manifest import LocalDocumentResolver
from .planner import ModelResearchPlanner
from .repository import SQLiteResearchRepository
from .service import ResearchControlPlane
from .team import ResearchTeamCoordinator, ResearchRoleModel
from .team_runtime import ResearchTeamRuntime
from .tools import EnterpriseResearchToolAdapter, LocalJsonSearchBackend, LocalResearchToolAdapter


class ResearchRuntimeService:
    def __init__(self, control_plane, tool_adapter, checkpointer, *, team_model,
                 stage_hook=None, checkpoint_connection=None, owns_repository=False):
        self.control_plane = control_plane
        self.tool_adapter = tool_adapter
        self.checkpoint_connection = checkpoint_connection
        self.owns_repository = owns_repository
        self.team = ResearchTeamCoordinator(control_plane, tool_adapter, team_model)
        self.team_runtime = ResearchTeamRuntime(control_plane, self.team, checkpointer, stage_hook=stage_hook)
        self.dispatcher = DurableDispatcher(control_plane, executor=self._execute,
                                            recovery_executor=self.team_runtime.resume)

    @classmethod
    def from_enterprise_catalog(cls, *, search_tool, read_tool, access_policy, **kwargs):
        if search_tool is None or read_tool is None or access_policy is None:
            raise ValueError("research_shared_tools_required")
        return cls.from_local_catalog(documents_dir=search_tool.documents_dir,
            search_tool=search_tool, read_tool=read_tool, access_policy=access_policy, **kwargs)

    @classmethod
    def from_local_catalog(cls, *, database_path, documents_dir, checkpoint_path=None,
                           id_factory=None, planner=None, team_model=None, stage_hook=None,
                           report_api_base=None, report_api_key=None, report_model=None,
                           search_tool=None, read_tool=None, access_policy: ResearchAccessPolicy | None = None):
        """Local adapter is for isolated tests; production supplies shared tools."""
        api_base = settings.LLM_API_BASE if report_api_base is None else report_api_base
        api_key = settings.LLM_API_KEY if report_api_key is None else report_api_key
        model = settings.LLM_MODEL if report_model is None else report_model
        repository = SQLiteResearchRepository(database_path)
        checkpoint_path = Path(checkpoint_path or Path(database_path).with_suffix('.graph.db'))
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        control = ResearchControlPlane(repository, source_resolver=LocalDocumentResolver(documents_dir),
            planner=planner or ModelResearchPlanner(api_base=api_base, api_key=api_key, model=model),
            id_factory=id_factory, access_policy=access_policy)
        adapter = (EnterpriseResearchToolAdapter(search_tool, read_tool, access_policy)
                   if search_tool is not None and access_policy is not None else
                   LocalResearchToolAdapter(LocalJsonSearchBackend(documents_dir), documents_dir))
        return cls(control, adapter, SqliteSaver(connection), team_model=team_model or
            ResearchRoleModel(api_base=api_base, api_key=api_key, model=model), stage_hook=stage_hook,
            checkpoint_connection=connection, owns_repository=True)

    def _execute(self, context):
        return self.team_runtime.run(context.job.research_id)

    def scan_once(self):
        return self.dispatcher.scan_once()

    def close(self):
        self.tool_adapter.close()
        if self.checkpoint_connection is not None:
            self.checkpoint_connection.close()
        if self.owns_repository:
            self.control_plane.repository.close()
