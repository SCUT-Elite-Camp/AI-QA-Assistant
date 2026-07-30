from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan


class IntentPolicyRouter:
    """Map QueryIntent to an allowlisted, immutable execution policy."""

    _POLICIES = {
        QueryIntent.KNOWLEDGE_QA: IntentPolicy(
            candidate_tools=("search_documents",),
        ),
        QueryIntent.DOCUMENT_SEARCH: IntentPolicy(
            candidate_tools=("search_documents",),
            retrieval_strategy="bm25",
            evidence_policy="document_identity",
            assembly_strategy="document_order",
            answer_style="document_list",
            top_k=10,
        ),
        QueryIntent.SUMMARIZATION: IntentPolicy(
            candidate_tools=("search_documents",),
            retrieval_strategy="hybrid",
            evidence_policy="topic_coverage",
            assembly_strategy="document_order",
            answer_style="structured_summary",
            top_k=10,
        ),
        QueryIntent.COMPARISON: IntentPolicy(
            candidate_tools=("search_documents",),
            retrieval_strategy="hybrid",
            evidence_policy="bilateral_coverage",
            assembly_strategy="group_by_target",
            answer_style="comparison_table",
            top_k=5,
        ),
        QueryIntent.CASUAL_CHAT: IntentPolicy(
            retrieval_strategy="none",
            evidence_policy="none",
            assembly_strategy="none",
            answer_style="direct_chat",
            top_k=0,
            max_iterations=1,
            max_tool_calls=0,
            max_retrieval_attempts=0,
            requires_citations=False,
        ),
        QueryIntent.SYSTEM_HELP: IntentPolicy(
            retrieval_strategy="none",
            evidence_policy="none",
            assembly_strategy="none",
            answer_style="capability_help",
            top_k=0,
            max_iterations=1,
            max_tool_calls=0,
            max_retrieval_attempts=0,
            requires_citations=False,
        ),
        QueryIntent.UNSUPPORTED: IntentPolicy(
            retrieval_strategy="none",
            evidence_policy="none",
            assembly_strategy="none",
            answer_style="unsupported",
            top_k=0,
            max_iterations=0,
            max_tool_calls=0,
            max_retrieval_attempts=0,
            requires_citations=False,
        ),
    }
    def route(self, query_plan: QueryPlan) -> IntentPolicy:
        """Return the fixed policy for the plan's validated intent."""
        return self._POLICIES[query_plan.intent]
