from typing import Any

import pytest

from agent.schemas.chat import AttachmentContext, ChatRequest, InternalChatRequest
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

            "tail": [],
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
