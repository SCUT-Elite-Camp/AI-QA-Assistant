from agent.orchestration.orchestrator import AgentOrchestrator
from agent.schemas.chat import ChatRequest, PersonalLibraryContext
from agent.schemas.intent_policy import IntentPolicy


def _request(query: str) -> ChatRequest:
    return ChatRequest(
        query=query,
        personal_library_context=PersonalLibraryContext(
            owner_user_id="user-a",
            knowledge_base_id="kb-a",
            access_token="0" * 64,
        ),
    )


def test_personal_query_enables_library_even_if_intent_was_casual():
    policy = IntentPolicy(
        retrieval_strategy="none",
        evidence_policy="none",
        assembly_strategy="none",
        answer_style="direct_chat",
        top_k=0,
        max_iterations=1,
        max_tool_calls=0,
        max_retrieval_attempts=0,
        requires_citations=False,
    )
    routed = AgentOrchestrator._apply_library_policy(_request("我的资料库里有哪些风险？"), policy)
    assert "search_library" in routed.candidate_tools
    assert routed.retrieval_strategy == "hybrid"


def test_enterprise_only_query_does_not_add_library_tool():
    policy = IntentPolicy(candidate_tools=("search_documents",))
    routed = AgentOrchestrator._apply_library_policy(_request("公司规定的报销标准是什么？"), policy)
    assert routed.candidate_tools == ("search_documents",)


def test_personal_enterprise_comparison_keeps_both_tools():
    policy = IntentPolicy(
        candidate_tools=("search_documents",),
        evidence_policy="bilateral_coverage",
        assembly_strategy="group_by_target",
        answer_style="comparison_table",
    )
    routed = AgentOrchestrator._apply_library_policy(
        _request("比较我的资料库里的方案和公司的 AI Governance Policy"),
        policy,
    )
    assert routed.candidate_tools == ("search_documents", "search_library")
