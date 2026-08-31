from agent.orchestration.orchestrator import AgentOrchestrator
from agent.schemas.chat import ChatRequest
from agent.schemas.intent_policy import IntentPolicy


def test_knowledge_base_retrieval_defaults_enabled() -> None:
    request = ChatRequest(query="查询企业制度")
    policy = IntentPolicy(candidate_tools=("search_documents",))

    assert request.knowledge_base_retrieval_enabled is True
    assert AgentOrchestrator._apply_knowledge_base_policy(request, policy) == policy


def test_disabled_knowledge_base_removes_all_library_tools() -> None:
    request = ChatRequest(
        query="直接回答",
        knowledge_base_retrieval_enabled=False,
    )
    policy = IntentPolicy(candidate_tools=(
        "search_documents",
        "find_documents",
        "get_document",
        "search_library",
    ))

    result = AgentOrchestrator._apply_knowledge_base_policy(request, policy)

    assert result.candidate_tools == ()
    assert result.retrieval_strategy == "none"
    assert result.max_retrieval_attempts == 0
    assert result.requires_citations is False


def test_disabled_knowledge_base_preserves_selected_attachment_tools() -> None:
    request = ChatRequest(
        query="这张图片里有什么？",
        knowledge_base_retrieval_enabled=False,
    )
    policy = IntentPolicy(candidate_tools=(
        "search_documents",
        "search_attachments",
        "inspect_attachment",
    ))

    result = AgentOrchestrator._apply_knowledge_base_policy(request, policy)

    assert result.candidate_tools == ("search_attachments", "inspect_attachment")
    assert result.retrieval_strategy == "hybrid"
    assert result.requires_citations is True
