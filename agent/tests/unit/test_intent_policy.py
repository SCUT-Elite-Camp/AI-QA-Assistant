import pytest
from pydantic import ValidationError

from agent.policy import IntentPolicyRouter
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan


pytestmark = pytest.mark.no_storage


def _plan(intent: QueryIntent) -> QueryPlan:
    return QueryPlan(
        original_query="test query",
        standalone_query="test query",
        intent=intent,
    )


@pytest.mark.parametrize(
    ("intent", "style", "uses_tools"),
    [
        (QueryIntent.KNOWLEDGE_QA, "concise_qa", True),
        (QueryIntent.DOCUMENT_SEARCH, "document_list", True),
        (QueryIntent.SUMMARIZATION, "structured_summary", True),
        (QueryIntent.COMPARISON, "comparison_table", True),
        (QueryIntent.CASUAL_CHAT, "direct_chat", False),
        (QueryIntent.SYSTEM_HELP, "capability_help", False),
        (QueryIntent.UNSUPPORTED, "unsupported", False),
    ],
)
def test_router_maps_every_intent_to_a_fixed_policy(
    intent: QueryIntent,
    style: str,
    uses_tools: bool,
) -> None:
    policy = IntentPolicyRouter().route(_plan(intent))

    assert policy.answer_style == style
    assert bool(policy.candidate_tools) is uses_tools
    assert (policy.retrieval_strategy != "none") is uses_tools


def test_non_tool_intents_have_zero_tool_and_retrieval_budgets() -> None:
    router = IntentPolicyRouter()

    for intent in (
        QueryIntent.CASUAL_CHAT,
        QueryIntent.SYSTEM_HELP,
        QueryIntent.UNSUPPORTED,
    ):
        policy = router.route(_plan(intent))
        assert policy.max_tool_calls == 0
        assert policy.max_retrieval_attempts == 0
        assert policy.requires_citations is False


def test_policy_is_immutable() -> None:
    policy = IntentPolicyRouter().route(_plan(QueryIntent.KNOWLEDGE_QA))

    with pytest.raises(ValidationError, match="frozen"):
        policy.top_k = 20


def test_policy_rejects_unknown_fields_and_unsafe_budgets() -> None:
    with pytest.raises(ValidationError):
        IntentPolicy(max_retrieval_attempts=6)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        IntentPolicy(model_selected_tool="delete_documents")
