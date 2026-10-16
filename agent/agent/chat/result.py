"""Request-local artifacts shared with the Chat response and Memory adapters."""

from dataclasses import dataclass
from typing import Any

from agent.policy import ChatRouteDecision
from agent.runtime.profile import ExecutionProfile
from agent.runtime.state import AgentRunResult
from agent.schemas.chat import ContextArtifact, MemoryRecall
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan


@dataclass(frozen=True)
class OrchestrationResult:
    """All internal artifacts produced by one orchestrated request."""

    query_plan: QueryPlan
    policy: IntentPolicy
    run_result: AgentRunResult | None
    history: list[dict[str, Any]]
    retrieval_mode: str
    top_k: int
    chat_route: ChatRouteDecision | None = None
    context_artifact: ContextArtifact | None = None
    memory_recall: MemoryRecall | None = None
    execution_profile: ExecutionProfile | None = None
