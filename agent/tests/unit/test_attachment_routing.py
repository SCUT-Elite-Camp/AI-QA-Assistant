from typing import Any

import pytest

from agent.orchestration.orchestrator import AgentOrchestrator
from agent.query.source_intent import heuristic_source_intent
from agent.runtime.runner import AgentRunner
from agent.schemas.chat import AttachmentContext, ChatRequest, InternalChatRequest
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan, SourceIntent, SourceKind
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistryAdapter
from toolset.tool_layer.attachment_tools import SearchAttachmentsTool
from toolset.tool_layer.registry import ToolRegistry


pytestmark = pytest.mark.no_storage


def _internal_request(query: str) -> InternalChatRequest:
    return InternalChatRequest(
        query=query,
        memory_context={
            "actor": {"user_id": "user-a", "authenticated": True},
            "chat_id": "chat-a",
            "revision": 1,
            "current_message_id": "message-a",
            "current_sequence": 1,
        },
        attachment_context=AttachmentContext(
            allowed_attachment_ids=["att_allowed"],
            selected_attachment_ids=["att_allowed"],
        ),
    )


def test_public_request_rejects_server_attachment_context() -> None:
    with pytest.raises(ValueError, match="trusted context"):
        ChatRequest.model_validate({
            "query": "summarize",
            "attachment_context": {
                "allowed_attachment_ids": ["att_allowed"],
                "selected_attachment_ids": ["att_allowed"],
            },
        })


def test_attachment_context_requires_prefixed_allowlisted_selection() -> None:
    with pytest.raises(ValueError, match="att_ prefix"):
        AttachmentContext(allowed_attachment_ids=["other"])
    with pytest.raises(ValueError, match="included in the allowlist"):
        AttachmentContext(
            allowed_attachment_ids=["att_allowed"],
            selected_attachment_ids=["att_other"],
        )


def test_attachment_source_policy_uses_only_trusted_context() -> None:
    intent = heuristic_source_intent("总结这份附件")
    assert intent.sources == [SourceKind.CONVERSATION_ATTACHMENT]

    enabled = AgentOrchestrator._apply_source_policy(
        _internal_request("总结这份附件"),
        IntentPolicy(candidate_tools=("search_documents",)),
        SourceIntent(sources=[SourceKind.CONVERSATION_ATTACHMENT]),
    )
    assert enabled.candidate_tools == ("search_attachments", "inspect_attachment")
    assert enabled.max_tool_calls >= 2

    disabled = AgentOrchestrator._apply_source_policy(
        ChatRequest(query="总结这份附件"),
        IntentPolicy(candidate_tools=("search_documents",)),
        SourceIntent(sources=[SourceKind.CONVERSATION_ATTACHMENT]),
    )
    assert disabled.candidate_tools == ()


def test_attachment_executor_preserves_citation_identity(monkeypatch) -> None:
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "secret")
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_allowed"], ["att_allowed"])

    def fake_request(_path: str, _payload: dict[str, Any], **_kwargs: Any):
        return {"items": [{
            "attachment_id": "att_allowed",
            "evidence_id": "aev_1",
            "filename": "report.pdf",
            "content": "attachment evidence",
            "score": 0.9,
            "locator": {"page": 2},
            "version": 3,
        }]}

    monkeypatch.setattr(tool, "_request", fake_request)
    executor = ToolExecutor(ToolRegistryAdapter(ToolRegistry(tools=[tool])))
    result = executor.execute(
        tool_call_id="call-1",
        tool_name="search_attachments",
        arguments={"query": "risk"},
        trace_id="trace-1",
    )

    assert result.success
    evidence = result.evidence[0]
    assert evidence.attachment_id == "att_allowed"
    assert evidence.evidence_id == "aev_1"
    assert evidence.locator == {"page": 2}
    assert evidence.version == 3
    assert evidence.source_type == "attachment"


def test_runner_overrides_attachment_search_query_and_budget() -> None:
    plan = QueryPlan(original_query="risk", standalone_query="resolved risk")
    constrained = AgentRunner._apply_execution_constraints(
        tool_name="search_attachments",
        arguments={"query": "model supplied", "top_k": 99},
        query_plan=plan,
        mode="hybrid",
        top_k=6,
    )
    assert constrained == {"query": "resolved risk", "top_k": 6}
