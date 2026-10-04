from agent.runtime.profile import ExecutionMode, ExecutionProfileResolver
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan, SourceIntent, SourceKind
from agent.schemas.chat import ChatRequest
from pydantic import ValidationError
import pytest


def _plan(intent: QueryIntent = QueryIntent.KNOWLEDGE_QA, **updates) -> QueryPlan:
    return QueryPlan(
        original_query="question",
        standalone_query="question",
        intent=intent,
        **updates,
    )


def test_explicit_thinking_resolves_to_thinking() -> None:
    resolver = ExecutionProfileResolver()
    policy = IntentPolicy()
    profile = resolver.resolve(
        "thinking", _plan(), policy, exploration_mode="auto",
        fast_retrieval_available=True,
    )
    assert profile.mode is ExecutionMode.THINKING
    assert profile.answer_model_preference == "complex"


def test_auto_uses_fast_only_for_supported_simple_qa() -> None:
    profile = ExecutionProfileResolver().resolve(
        "auto", _plan(), IntentPolicy(candidate_tools=("search_documents",)),
        exploration_mode="auto", fast_retrieval_available=True,
    )
    assert profile.mode is ExecutionMode.FAST
    assert profile.reason == "auto_default_fast"


def test_omitted_mode_defaults_to_fast_for_supported_simple_qa() -> None:
    assert ChatRequest(query="question").weight_mode == "fast"
    profile = ExecutionProfileResolver().resolve(
        None, _plan(), IntentPolicy(candidate_tools=("search_documents",)),
        exploration_mode="auto", fast_retrieval_available=True,
    )
    assert profile.requested_mode == "fast"
    assert profile.mode is ExecutionMode.FAST


def test_auto_and_explicit_fast_fall_back_for_complex_or_unsupported_plans() -> None:
    resolver = ExecutionProfileResolver()
    policy = IntentPolicy(candidate_tools=("search_documents",))
    cases = [
        (_plan(QueryIntent.COMPARISON, sub_queries=["A", "B"]), "auto", "planned_subqueries"),
        (_plan(), "fast", "fast_fallback:forced_exploration"),
        (_plan(source_intent=SourceIntent(sources=[SourceKind.PERSONAL_LIBRARY])), "fast", "fast_fallback:private_source_unsupported"),
        (_plan(), "fast", "fast_fallback:unsupported_intent_or_policy"),
    ]
    for plan, mode, reason in cases:
        profile = resolver.resolve(
            mode, plan, policy,
            exploration_mode="force" if reason.endswith("forced_exploration") else "auto",
            fast_retrieval_available=(reason != "fast_fallback:unsupported_intent_or_policy"),
        )
        assert profile.mode is ExecutionMode.THINKING
        expected_reason = (
            "auto_fallback:planned_subqueries"
            if mode == "auto"
            else reason
        )
        assert profile.reason == expected_reason


@pytest.mark.parametrize("legacy_mode", ["deeper", "wider"])
def test_request_contract_rejects_retired_modes(legacy_mode: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="question", weight_mode=legacy_mode)
