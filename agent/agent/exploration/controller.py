from collections.abc import Iterable

from agent.exploration.coverage import CoverageAssessor
from agent.exploration.schemas import CoverageAssessment, ExplorationAction
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence


class ExplorationController:
    """Own the single decision point for starting bounded Wiki exploration."""

    def __init__(self, assessor: CoverageAssessor | None = None) -> None:
        self.assessor = assessor or CoverageAssessor()

    def assess_after_direct(
        self,
        query_plan: QueryPlan,
        accepted_evidence: Iterable[Evidence],
        *,
        exploration_mode: str,
        wiki_available: bool,
    ) -> CoverageAssessment:
        actions = (
            (ExplorationAction.WIKI_SEARCH,)
            if wiki_available
            else ()
        )
        return self.assessor.assess(
            query_plan,
            accepted_evidence,
            exploration_mode=exploration_mode,
            available_actions=actions,
        )
