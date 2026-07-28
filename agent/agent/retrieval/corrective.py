from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from agent.evidence.schemas import EvidenceGateResult
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    top_k: int = Field(ge=1, le=20)
    mode: str
    filters: dict = Field(default_factory=dict)
    retrieval_attempt: int = Field(ge=1, le=2)


class CorrectiveRetrievalPlanner:
    """Create one bounded second-attempt retrieval plan."""

    _FALLBACK_MODE = {
        "hybrid": "bm25",
        "bm25": "vector",
        "vector": "bm25",
    }

    def plan(
        self,
        query_plan: QueryPlan,
        policy: IntentPolicy,
        gate_result: EvidenceGateResult,
        *,
        previous_mode: str,
        previous_top_k: int,
    ) -> list[RetrievalRequest]:
        if not gate_result.should_retry:
            return []
        if gate_result.retrieval_attempt != 1:
            raise ValueError("corrective retrieval may only follow attempt one")
        if previous_mode not in self._FALLBACK_MODE:
            raise ValueError("previous_mode must be vector, bm25, or hybrid")
        if not 1 <= previous_top_k <= 20:
            raise ValueError("previous_top_k must be between one and twenty")

        queries = (
            gate_result.missing_targets
            if gate_result.missing_targets
            else [query_plan.standalone_query]
        )
        next_top_k = min(20, max(previous_top_k, policy.top_k) * 2)
        next_mode = self._FALLBACK_MODE[previous_mode]

        return [
            RetrievalRequest(
                query=query,
                top_k=next_top_k,
                mode=next_mode,
                filters=deepcopy(query_plan.filters),
                retrieval_attempt=2,
            )
            for query in queries
        ]
