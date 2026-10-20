import hashlib
import hmac
import json
from typing import Any

import pytest

from agent.schemas.chat import ChatRequest, InternalChatRequest, PersonalLibraryContext
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistryAdapter
from toolset.tool_layer.registry import ToolRegistry
from toolset.tool_layer.search_library_tool import SearchLibraryTool


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
        personal_library_context=PersonalLibraryContext(
            owner_user_id="user-a",
            knowledge_base_id="kb-a",
            access_token="0" * 64,
        ),
    )


def test_public_request_rejects_server_library_context() -> None:
    with pytest.raises(ValueError, match="trusted context"):
        ChatRequest.model_validate({
            "query": "risk",
            "personal_library_context": {
                "owner_user_id": "user-a",
                "knowledge_base_id": "kb-a",
                "access_token": "0" * 64,
            },
        })


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"items": [{
            "evidence_id": "ver-a_chunk_12",
            "knowledge_base_id": "kb-a",
            "document_id": "doc-a",
            "version_id": "ver-a",
            "source_scope": "personal",
            "filename": "risk.md",
            "content": "personal evidence",
            "score": 0.9,
            "locator": {"section_path": ["Risk"]},
        }]}).encode()


def test_executor_propagates_request_context_and_preserves_evidence(monkeypatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    monkeypatch.setattr("toolset.tool_layer.search_library_tool.search_library_evidence", lambda *_args, **_kwargs: json.loads(_Response().read()))
    tool = SearchLibraryTool()
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool.set_request_context("user-a", "kb-a", token)
    executor = ToolExecutor(ToolRegistryAdapter(ToolRegistry(tools=[tool])))

    result = executor.execute(
        tool_call_id="call-1",
        tool_name="search_library",
        arguments={"query": "risk"},
        trace_id="trace-1",
    )

    assert result.success
    evidence = result.evidence[0]
    assert evidence.doc_id == "doc-a"
    assert evidence.chunk_id == "ver-a_chunk_12"
    assert evidence.source_type == "personal"
    assert evidence.knowledge_base_id == "kb-a"
    assert evidence.version_id == "ver-a"
    assert evidence.locator == {"section_path": ["Risk"]}
