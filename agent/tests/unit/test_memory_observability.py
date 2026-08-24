from __future__ import annotations

import pytest

from agent.agent import Agent
from agent.config.settings import settings
from agent.memory.memory_observability import MemoryObservability
from agent.orchestration import OrchestrationResult
from agent.runtime import AgentRunResult, StopReason
from agent.schemas.chat import (
    ContextArtifact,
    InternalChatRequest,
    MemoryRecall,
    MemoryMessage,
)
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan


class _RequestContextToolExecutor:
    def set_request_context(self, **_kwargs: object) -> object:
        return object()

    def reset_request_context(self, _token: object) -> None:
        return None


class _CitationCheck:
    valid = True
    errors: list[str] = []


class _FixedOrchestrator:
    def __init__(self, result: OrchestrationResult) -> None:
        self._result = result

    def run(self, *_args: object, **_kwargs: object) -> OrchestrationResult:
        return self._result

    def validate_citations(self, *_args: object, **_kwargs: object) -> _CitationCheck:
        return _CitationCheck()


def _trusted_request() -> InternalChatRequest:
    return InternalChatRequest.model_validate(
        {
            "query": "Use the prior context.",
            "session_id": "chat-1",
            "is_first_message": False,
            "memory_context": {
                "actor": {"user_id": "user-1", "authenticated": True},
                "chat_id": "chat-1",
                "revision": 1,
                "current_message_id": "message-2",
                "current_sequence": 2,
                "snapshot": None,
                "facts": [],
                "tail": [],
            },
        }
    )


def _orchestration_result(*, recall: MemoryRecall | None = None) -> OrchestrationResult:
    artifact = ContextArtifact(
        memory_brief="",
        model_history=[
            MemoryMessage(
                id="system-memory",
                sequence=1,
                revision=1,
                role="system",
                content="Memory context",
            ),
            MemoryMessage(
                id="message-1",
                sequence=2,
                revision=1,
                role="user",
                content="Prior message",
            ),
        ],
        metadata={"source": "persistent_memory"},
    )
    return OrchestrationResult(
        query_plan=QueryPlan(
            original_query="Use the prior context.",
            standalone_query="Use the prior context.",
        ),
        policy=IntentPolicy(),
        run_result=(
            None
            if recall is not None
            else AgentRunResult(stop_reason=StopReason.FINAL_ANSWER, answer="answer")
        ),
        history=[],
        retrieval_mode="hybrid",
        top_k=5,
        context_artifact=artifact,
        memory_recall=recall,
    )


def test_observability_emits_only_documented_content_free_payloads() -> None:
    events: list[tuple[str, dict[str, str | int]]] = []
    observability = MemoryObservability(
        emit=lambda event, payload: events.append((event, payload))
    )

    observability.resolve(
        source="trusted_context",
        outcome="success",
        duration_ms=7,
    )
    observability.compaction(
        outcome="planned",
        tail_count=8,
        snapshot_version=2,
    )
    observability.fact(action="recalled", outcome="success")
    observability.prompt(model_history_chars=18)

    assert events == [
        (
            "memory_resolve",
            {"source": "trusted_context", "outcome": "success", "duration_ms": 7},
        ),
        (
            "memory_compaction",
            {"outcome": "planned", "tail_count": 8, "snapshot_version": 2},
        ),
        ("memory_fact", {"action": "recalled", "outcome": "success"}),
        ("memory_prompt", {"model_history_chars": 18}),
    ]
    forbidden = {
        "fact",
        "value",
        "summary",
        "tail",
        "query",
        "prompt",
        "message_id",
        "chat_id",
        "token",
    }
    assert all(not (forbidden & set(payload)) for _, payload in events)


@pytest.mark.parametrize(
    "call",
    [
        lambda observer: observer.resolve(
            source="untrusted",  # type: ignore[arg-type]
            outcome="success",
            duration_ms=1,
        ),
        lambda observer: observer.resolve(
            source="legacy",
            outcome="unexpected",  # type: ignore[arg-type]
            duration_ms=1,
        ),
        lambda observer: observer.resolve(
            source="legacy",
            outcome="success",
            duration_ms=-1,
        ),
        lambda observer: observer.compaction(
            outcome="skipped",
            tail_count=0,
            snapshot_version=0,
        ),
        lambda observer: observer.fact(
            action="stored",  # type: ignore[arg-type]
            outcome="success",
        ),
        lambda observer: observer.prompt(model_history_chars=-1),
    ],
)
def test_observability_rejects_unknown_labels_and_invalid_numbers(call) -> None:
    with pytest.raises(ValueError):
        call(MemoryObservability(emit=lambda _event, _payload: None))


def test_observability_sink_failure_does_not_escape() -> None:
    def fail_sink(_event: str, _payload: dict[str, str | int]) -> None:
        raise RuntimeError("user content must not be logged")

    MemoryObservability(emit=fail_sink).fact(action="suppressed", outcome="failed")


def test_prompt_length_is_emitted_only_after_runner_uses_trusted_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, str | int]]] = []
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    agent = Agent(
        tools=[],
        tool_executor=_RequestContextToolExecutor(),  # type: ignore[arg-type]
        orchestrator=_FixedOrchestrator(_orchestration_result()),  # type: ignore[arg-type]
        memory_observability=MemoryObservability(
            emit=lambda event, payload: events.append((event, payload))
        ),
    )

    response, _ = agent.chat_with_memory(_trusted_request())

    assert response.status == "success"
    prompt_events = [event for event in events if event[0] == "memory_prompt"]
    assert prompt_events == [("memory_prompt", {"model_history_chars": 27})]
    assert "Use the prior context." not in repr(events)
    assert "Memory context" not in repr(events)


def test_prompt_length_is_not_emitted_for_exact_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, str | int]]] = []
    monkeypatch.setattr(settings, "PERSISTENT_MEMORY_ENABLED", True)
    agent = Agent(
        tools=[],
        tool_executor=_RequestContextToolExecutor(),  # type: ignore[arg-type]
        orchestrator=_FixedOrchestrator(
            _orchestration_result(recall=MemoryRecall(handled=True, answer="saved goal"))
        ),  # type: ignore[arg-type]
        memory_observability=MemoryObservability(
            emit=lambda event, payload: events.append((event, payload))
        ),
    )

    response, _ = agent.chat_with_memory(_trusted_request())

    assert response.answer == "saved goal"
    assert all(event != "memory_prompt" for event, _payload in events)
