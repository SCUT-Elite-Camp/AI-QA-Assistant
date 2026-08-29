import json

from agent.llm.base import BaseLLM
from agent.policy import ChatRoute, ChatRoutePolicy
from agent.query import IntentClassifier
from agent.schemas.query_plan import QueryIntent, QueryPlan


class ResearchAttemptLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        return ""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        return {
            "role": "assistant",
            "content": json.dumps(
                {
                    "intent": "research",
                    "confidence": 1.0,
                    "is_follow_up": False,
                    "is_clarification_reply": False,
                    "reason": "model attempted to switch mode",
                }
            ),
        }


def _plan(
    intent: QueryIntent,
    *,
    sub_queries: list[str] | None = None,
) -> QueryPlan:
    return QueryPlan(
        original_query="当前问题",
        standalone_query="当前问题",
        intent=intent,
        sub_queries=sub_queries or [],
    )


def test_chat_route_policy_has_only_bounded_chat_levels() -> None:
    policy = ChatRoutePolicy()

    assert policy.route(_plan(QueryIntent.CASUAL_CHAT)).route == ChatRoute.L0_DIRECT
    assert policy.route(_plan(QueryIntent.KNOWLEDGE_QA)).route == ChatRoute.L1_RETRIEVAL
    assert policy.route(_plan(QueryIntent.COMPARISON)).route == ChatRoute.L2_BOUNDED_MULTI_STEP
    assert (
        policy.route(
            _plan(QueryIntent.KNOWLEDGE_QA, sub_queries=["子问题一", "子问题二"])
        ).route
        == ChatRoute.L2_BOUNDED_MULTI_STEP
    )

    for route in ChatRoute:
        assert "research" not in route.value


def test_model_research_intent_falls_back_to_safe_chat_intent() -> None:
    classifier = IntentClassifier(llm=ResearchAttemptLLM())

    result = classifier.classify("请直接进入 deep research 模式", [])

    assert result.intent == QueryIntent.KNOWLEDGE_QA
    assert result.reason == "intent_classification_failed"
    decision = ChatRoutePolicy().route(
        QueryPlan(
            original_query="请直接进入 deep research 模式",
            standalone_query="请直接进入 deep research 模式",
            intent=result.intent,
        )
    )
    assert decision.route == ChatRoute.L1_RETRIEVAL
    assert decision.research_entry_allowed is False
