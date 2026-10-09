"""Resolve public execution preferences into a small internal strategy contract."""

from dataclasses import dataclass
from enum import StrEnum

from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceKind


class ExecutionMode(StrEnum):
    FAST = "fast"
    THINKING = "thinking"


@dataclass(frozen=True)
class ExecutionProfile:
    requested_mode: str
    mode: ExecutionMode
    exploration_mode: str
    reason: str
    answer_model_preference: str


class ExecutionProfileResolver:
    """Purely map a request plan and policy to a supported execution strategy."""

    def resolve(
        self,
        requested_mode: str | None,
        plan: QueryPlan,
        policy: IntentPolicy,
        *,
        exploration_mode: str,
        fast_retrieval_available: bool,
    ) -> ExecutionProfile:
        requested = (requested_mode or "fast").strip().lower()
        if requested not in {"fast", "thinking", "auto"}:
            requested = "thinking"

        eligible, reason = self._fast_eligibility(
            plan,
            policy,
            exploration_mode=exploration_mode,
            fast_retrieval_available=fast_retrieval_available,
        )
        if requested == "thinking":
            return ExecutionProfile(requested, ExecutionMode.THINKING, exploration_mode,
                                    "explicit_thinking", "complex")
        if requested == "auto":
            # Auto currently starts on the Fast strategy; eligibility checks
            # remain the correctness boundary until adaptive routing exists.
            mode = ExecutionMode.FAST if eligible else ExecutionMode.THINKING
            effective_exploration = "off" if mode == ExecutionMode.FAST else exploration_mode
            return ExecutionProfile(requested, mode, effective_exploration,
                                    "auto_default_fast" if eligible else f"auto_fallback:{reason}",
                                    "fast" if eligible else "complex")
        if requested == "fast":
            mode = ExecutionMode.FAST if eligible else ExecutionMode.THINKING
            effective_exploration = "off" if mode == ExecutionMode.FAST else exploration_mode
            return ExecutionProfile(requested, mode, effective_exploration,
                                    "explicit_fast" if eligible else f"fast_fallback:{reason}",
                                    "fast" if eligible else "complex")
        return ExecutionProfile(requested, ExecutionMode.THINKING, exploration_mode,
                                "default_thinking", "complex")

    @staticmethod
    def _fast_eligibility(
        plan: QueryPlan,
        policy: IntentPolicy,
        *,
        exploration_mode: str,
        fast_retrieval_available: bool,
    ) -> tuple[bool, str]:
        if plan.needs_clarification:
            return False, "clarification_required"
        if plan.sub_queries:
            return False, "planned_subqueries"
        if plan.needs_structure or plan.needs_version_reasoning or plan.scope == "multi_doc":
            return False, "complex_plan_shape"
        if exploration_mode == "force":
            return False, "forced_exploration"
        private_sources = {
            SourceKind.PERSONAL_LIBRARY,
            SourceKind.CONVERSATION_ATTACHMENT,
        }
        if private_sources.intersection(plan.source_intent.sources):
            return False, "private_source_unsupported"
        if plan.intent in {QueryIntent.CASUAL_CHAT, QueryIntent.SYSTEM_HELP}:
            return policy.retrieval_strategy == "none", "no_retrieval_policy"
        if (
            plan.intent == QueryIntent.KNOWLEDGE_QA
            and policy.retrieval_strategy in {"vector", "bm25", "hybrid"}
            and policy.evidence_policy == "single_fact"
            and policy.requires_citations
            and "search_documents" in policy.candidate_tools
            and fast_retrieval_available
        ):
            return True, "direct_enterprise_qa"
        return False, "unsupported_intent_or_policy"
