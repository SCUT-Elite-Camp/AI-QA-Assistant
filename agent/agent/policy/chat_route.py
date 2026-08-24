"""Deterministic L0/L1/L2 routing for the ordinary Chat path.

The policy is intentionally a Chat-only policy.  There is no Research route
in this enum and no model-controlled field that can create or switch to a
Research job.  Research will have a separate, manual entry point in a later
week.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from agent.schemas.query_plan import QueryIntent, QueryPlan


class ChatRoute(StrEnum):
    """The three bounded execution levels available to ordinary Chat."""

    L0_DIRECT = "chat_l0_direct"
    L1_RETRIEVAL = "chat_l1_retrieval"
    L2_BOUNDED_MULTI_STEP = "chat_l2_bounded_multi_step"


@dataclass(frozen=True)
class ChatRouteDecision:
    """Internal route metadata; it is never exposed as a Web field."""

    route: ChatRoute
    reason: str
    research_entry_allowed: bool = field(default=False, init=False)


class ChatRoutePolicy:
    """Map a validated QueryPlan to a bounded Chat-only route."""

    _DIRECT_INTENTS = frozenset(
        {
            QueryIntent.CASUAL_CHAT,
            QueryIntent.SYSTEM_HELP,
            QueryIntent.UNSUPPORTED,
        }
    )

    def route(self, query_plan: QueryPlan) -> ChatRouteDecision:
        """Return a deterministic route without consulting model text."""

        if query_plan.intent in self._DIRECT_INTENTS:
            return ChatRouteDecision(
                route=ChatRoute.L0_DIRECT,
                reason=f"intent:{query_plan.intent.value}",
            )

        if query_plan.intent == QueryIntent.COMPARISON or query_plan.sub_queries:
            return ChatRouteDecision(
                route=ChatRoute.L2_BOUNDED_MULTI_STEP,
                reason=(
                    "comparison_intent"
                    if query_plan.intent == QueryIntent.COMPARISON
                    else "bounded_sub_queries"
                ),
            )

        return ChatRouteDecision(
            route=ChatRoute.L1_RETRIEVAL,
            reason=f"intent:{query_plan.intent.value}",
        )


__all__ = ["ChatRoute", "ChatRouteDecision", "ChatRoutePolicy"]
