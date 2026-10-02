"""Internal routing artifacts for decomposed queries."""

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent


class SubQueryRoute(BaseModel):
    """Intent and execution policy selected for one decomposed sub-query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    policy: IntentPolicy


class SubQueryRoutingResult(BaseModel):
    """Request-local routing result; deliberately not part of public QueryPlan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_complex: bool = False
    routes: tuple[SubQueryRoute, ...] = ()
