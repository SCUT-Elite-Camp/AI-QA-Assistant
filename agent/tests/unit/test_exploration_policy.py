from agent.config.settings import settings
from agent.orchestration.orchestrator import AgentOrchestrator
from agent.schemas.chat import ChatRequest, InternalChatRequest, PersonalLibraryContext
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan, SourceIntent, SourceKind


def _plan() -> QueryPlan:
    return QueryPlan(
        original_query="Agent 层完成了什么工作？",
        standalone_query="Agent 层完成了什么工作？",
    )


def test_wiki_tools_require_an_authorized_source_scope(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AGENTIC_EXPLORATION_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_NAVIGATION_ENABLED", True)
    policy = IntentPolicy(candidate_tools=("search_documents",))

    result = AgentOrchestrator._apply_exploration_policy(
        ChatRequest(query=_plan().original_query), _plan(), policy,
        navigation_scopes=(),
    )

    assert result == policy


def test_navigation_scopes_follow_effective_source_and_request_context() -> None:
    # The personal-library scope is populated only by the trusted internal
    # endpoint.  Construct that already-validated state directly so this unit
    # test remains focused on scope derivation rather than endpoint validation.
    request = InternalChatRequest.model_construct(
        query=_plan().original_query,
        personal_library_context=PersonalLibraryContext(
            owner_user_id="user-1",
            knowledge_base_id="kb-personal",
            access_token="a" * 64,
        ),
    )
    both = AgentOrchestrator._navigation_scopes(
        request,
        SourceIntent(sources=[SourceKind.ENTERPRISE_KB, SourceKind.PERSONAL_LIBRARY]),
    )
    disabled = AgentOrchestrator._navigation_scopes(
        request.model_copy(update={"knowledge_base_retrieval_enabled": False}),
        SourceIntent(sources=[SourceKind.ENTERPRISE_KB, SourceKind.PERSONAL_LIBRARY]),
    )

    assert both == ("enterprise", "personal")
    assert disabled == ()
