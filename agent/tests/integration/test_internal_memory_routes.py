from __future__ import annotations

import sys
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app as app_module
from agent.agent import Agent
from agent.api import chat_routes
from agent.api.chat_routes import get_agent, router as public_chat_router
from agent.api.internal_memory_routes import router as internal_memory_router
from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.runtime import lifecycle
from agent.runtime.lifecycle import ApplicationContainer
from agent.schemas.chat import ChatRequest, ChatResponse, MemoryDecision
from toolset.tool_layer.registry import ToolRegistry


production_app = app_module.app


@dataclass
class RecordingMemory:
    cleared_chat_ids: list[str] = field(default_factory=list)

    def clear(self, chat_id: str) -> None:
        self.cleared_chat_ids.append(chat_id)


@dataclass
class RecordingAgent:
    memory: RecordingMemory = field(default_factory=RecordingMemory)
    requests: list[ChatRequest] = field(default_factory=list)

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            trace_id="trace-internal-memory",
            status="success",
            answer="A controlled answer.",
            message="",
            citations=[],
        )

    def chat_with_memory(
        self,
        request: ChatRequest,
    ) -> tuple[ChatResponse, MemoryDecision]:
        return self.chat(request), MemoryDecision(fact_proposals=[])


class LifecycleStubLLM(BaseLLM):
    """Avoid external model access while exercising the production lifespan."""

    def generate(self, prompt: str) -> str:
        return "stub"

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        return {"role": "assistant", "content": "stub"}


class DeepResearchImportGuard:
    """Fail if a Chat/Memory request ever starts loading Deep Research."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> None:
        if fullname == "deep_research" or fullname.startswith("deep_research."):
            raise AssertionError("Chat and Memory endpoints must not load Deep Research")
        return None


@pytest.fixture
def internal_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, RecordingAgent]:
    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)

    application = FastAPI()
    application.include_router(public_chat_router, prefix="/api")
    application.include_router(internal_memory_router, prefix="/api/internal")
    agent = RecordingAgent()
    application.dependency_overrides[get_agent] = lambda: agent
    return TestClient(application), agent


def _headers(token: str = "internal-token") -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Agent-Internal-Token": token,
    }


def _memory_context() -> dict[str, object]:
    return {
        "actor": {"user_id": "user-1", "authenticated": True},
        "chat_id": "chat-1",
        "revision": 1,
        "current_message_id": "message-3",
        "current_sequence": 3,
        "snapshot": {
            "id": "snapshot-1",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 1,
            "summary": "Earlier discussion.",
        },
        "facts": [],
        "tail": [
            {
                "id": "message-2",
                "sequence": 2,
                "revision": 1,
                "role": "assistant",
                "content": "Earlier answer.",
            }
        ],
    }


def _internal_chat_payload() -> dict[str, object]:
    return {
        "query": "What did we discuss?",
        "session_id": "chat-1",
        "memory_context": _memory_context(),
    }


def _compaction_payload() -> dict[str, object]:
    return {
        "actor": {"user_id": "user-1", "authenticated": True},
        "chat_id": "chat-1",
        "revision": 1,
        "active_snapshot": None,
        "messages": [],
        "tail_size": 8,
        "min_coverable_messages": 12,
        "soft_token_budget": 1000,
    }


def _compaction_messages(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"message-{sequence}",
            "sequence": sequence,
            "revision": 1,
            "role": "user" if sequence % 2 else "assistant",
            "content": f"persisted message {sequence}",
        }
        for sequence in range(1, count + 1)
    ]


def test_production_application_registers_only_the_private_memory_routes() -> None:
    assert str(production_app.url_path_for("internal_chat")) == "/api/internal/chat"
    assert (
        str(production_app.url_path_for("compaction_plan"))
        == "/api/internal/memory/compaction-plan"
    )
    assert (
        str(production_app.url_path_for("reset_short_window"))
        == "/api/internal/memory/reset-short-window"
    )


def test_production_lifespan_reuses_one_agent_without_deep_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real app lifespan and prove request paths stay on one Agent."""

    monkeypatch.setattr(settings, "AGENT_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)

    constructed_agents: list[Agent] = []
    chat_requests: list[ChatRequest] = []
    original_init = Agent.__init__

    def counting_init(self: Agent, *args: object, **kwargs: object) -> None:
        constructed_agents.append(self)
        original_init(self, *args, **kwargs)

    def controlled_chat(self: Agent, request: ChatRequest) -> ChatResponse:
        chat_requests.append(request)
        return ChatResponse(
            trace_id="trace-production-lifecycle",
            status="success",
            answer="A controlled answer.",
            message="",
            citations=[],
        )

    def controlled_memory_chat(
        self: Agent,
        request: ChatRequest,
    ) -> tuple[ChatResponse, MemoryDecision]:
        return controlled_chat(self, request), MemoryDecision(fact_proposals=[])

    container = ApplicationContainer(
        llm_factory=LifecycleStubLLM,
        registry_factory=lambda: ToolRegistry(tools=[]),
    )
    guard = DeepResearchImportGuard()
    deep_research_modules = [
        name
        for name in sys.modules
        if name == "deep_research" or name.startswith("deep_research.")
    ]
    for module_name in deep_research_modules:
        monkeypatch.delitem(sys.modules, module_name)
    monkeypatch.setattr(lifecycle.Agent, "__init__", counting_init)
    monkeypatch.setattr(Agent, "chat", controlled_chat)
    monkeypatch.setattr(Agent, "chat_with_memory", controlled_memory_chat)
    monkeypatch.setattr(app_module, "get_application_container", lambda: container)
    monkeypatch.setattr(chat_routes, "get_application_container", lambda: container)
    monkeypatch.setattr(sys, "meta_path", [guard, *sys.meta_path])

    with TestClient(production_app) as client:
        assert production_app.state.application_container is container
        assert container.snapshot().initialization_count == 1
        assert len(constructed_agents) == 1

        public_response = client.post("/api/chat", json={"query": "Public question"})
        internal_response = client.post(
            "/api/internal/chat",
            json=_internal_chat_payload(),
            headers=_headers(),
        )
        compaction_response = client.post(
            "/api/internal/memory/compaction-plan",
            json=_compaction_payload(),
            headers=_headers(),
        )

        assert public_response.status_code == 200
        assert internal_response.status_code == 200
        assert compaction_response.status_code == 200
        assert compaction_response.json() == {"should_compact": False}
        assert len(chat_requests) == 2
        assert len(constructed_agents) == 1
        assert container.snapshot().initialization_count == 1


def test_internal_endpoints_reject_missing_and_invalid_tokens(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    missing = client.post("/api/internal/chat", json=_internal_chat_payload())
    invalid = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers("wrong-token"),
    )

    assert missing.status_code == invalid.status_code == 403
    assert missing.json() == invalid.json() == {"detail": "forbidden"}
    assert agent.requests == []


def test_internal_authentication_precedes_request_body_validation(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, _ = internal_client

    response = client.post("/api/internal/chat", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_internal_endpoints_require_json_content_type(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    response = client.post(
        "/api/internal/memory/reset-short-window",
        content='{"chat_id":"chat-1"}',
        headers={
            "Content-Type": "text/plain",
            "X-Agent-Internal-Token": "internal-token",
        },
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "unsupported_media_type"}
    assert agent.memory.cleared_chat_ids == []


def test_public_chat_rejects_internal_memory_context(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, _ = internal_client

    response = client.post("/api/chat", json=_internal_chat_payload())

    assert response.status_code == 422
    assert "memory_context" in response.text


def test_internal_chat_returns_fixed_409_when_persistent_memory_is_disabled(
    internal_client: tuple[TestClient, RecordingAgent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, agent = internal_client
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)

    response = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {"code": "persistent_memory_disabled"}
    assert agent.requests == []


def test_internal_chat_uses_shared_agent_and_returns_empty_fact_proposals(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client

    response = client.post(
        "/api/internal/chat",
        json=_internal_chat_payload(),
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["response"]["trace_id"] == "trace-internal-memory"
    assert response.json()["memory_decision"]["fact_proposals"] == []
    assert len(agent.requests) == 1


def test_internal_chat_rejects_memory_context_revision_mismatch(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _internal_chat_payload()
    payload["memory_context"]["snapshot"]["revision"] = 2

    response = client.post(
        "/api/internal/chat",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_memory_context"}
    assert agent.requests == []


def test_compaction_is_a_noop_and_reset_clears_only_short_window(
    internal_client: tuple[TestClient, RecordingAgent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, agent = internal_client
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", False)

    compaction = client.post(
        "/api/internal/memory/compaction-plan",
        json=_compaction_payload(),
        headers=_headers(),
    )
    reset = client.post(
        "/api/internal/memory/reset-short-window",
        json={"chat_id": "chat-1"},
        headers=_headers(),
    )

    assert compaction.status_code == 200
    assert compaction.json() == {"should_compact": False}
    assert reset.status_code == 200
    assert reset.json() == {"status": "ok"}
    assert agent.memory.cleared_chat_ids == ["chat-1"]
    assert agent.requests == []


def test_compaction_returns_a_pure_plan_without_using_the_shared_agent(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _compaction_payload()
    payload["messages"] = _compaction_messages(20)

    response = client.post(
        "/api/internal/memory/compaction-plan",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "should_compact": True,
        "expected_active_snapshot": None,
        "new_snapshot": {
            "covered_from_sequence": 1,
            "covered_to_sequence": 12,
            "covered_from_message_id": "message-1",
            "covered_to_message_id": "message-12",
            "summary": "[New covered messages]\n"
            "- user: persisted message 1\n"
            "- assistant: persisted message 2\n"
            "- user: persisted message 3\n"
            "- assistant: persisted message 4\n"
            "- user: persisted message 5\n"
            "- assistant: persisted message 6\n"
            "- user: persisted message 7\n"
            "- assistant: persisted message 8\n"
            "- user: persisted message 9\n"
            "- assistant: persisted message 10\n"
            "- user: persisted message 11\n"
            "- assistant: persisted message 12",
        },
    }
    assert agent.requests == []
    assert agent.memory.cleared_chat_ids == []


def test_compaction_rejects_non_current_revision_messages(
    internal_client: tuple[TestClient, RecordingAgent],
) -> None:
    client, agent = internal_client
    payload = _compaction_payload()
    payload["messages"] = [
        {
            "id": "message-1",
            "sequence": 1,
            "revision": 2,
            "role": "user",
            "content": "stale revision",
        }
    ]

    response = client.post(
        "/api/internal/memory/compaction-plan",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_memory_context"}
    assert agent.requests == []
