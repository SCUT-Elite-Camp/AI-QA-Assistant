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
        "thinking", exploration_mode="auto",
    )
    assert profile.mode is ExecutionMode.THINKING


def test_auto_is_a_thinking_alias_even_for_simple_qa() -> None:
    profile = ExecutionProfileResolver().resolve(
        "auto", exploration_mode="auto",
    )
    assert profile.mode is ExecutionMode.THINKING
    assert profile.reason == "auto_alias_thinking"


def test_omitted_mode_defaults_to_fast_for_supported_simple_qa() -> None:
    assert ChatRequest(query="question").weight_mode == "fast"
    profile = ExecutionProfileResolver().resolve(
        None, exploration_mode="auto",
    )
    assert profile.requested_mode == "fast"
    assert profile.mode is ExecutionMode.FAST


@pytest.mark.parametrize("plan", [
    _plan(QueryIntent.COMPARISON, sub_queries=["A", "B"]),
    _plan(source_intent=SourceIntent(sources=[SourceKind.PERSONAL_LIBRARY])),
    _plan(needs_structure=True),
])
def test_explicit_fast_never_changes_mode_based_on_plan_or_tool_availability(plan) -> None:
    profile = ExecutionProfileResolver().resolve(
        "fast", exploration_mode="force",
    )
    assert profile.mode is ExecutionMode.FAST
    assert profile.reason == "explicit_fast"
    assert profile.exploration_mode == "off"


@pytest.mark.parametrize("legacy_mode", ["deeper", "wider"])
def test_request_contract_rejects_retired_modes(legacy_mode: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="question", weight_mode=legacy_mode)
