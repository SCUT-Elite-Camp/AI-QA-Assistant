import pytest

from agent.llm.observability import (
    ObservedLLM,
    clear_llm_metrics,
    snapshot_llm_metrics,
    start_llm_metrics,
)


pytestmark = pytest.mark.no_storage


class StubLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None, **kwargs) -> dict:
        if self.fail:
            raise RuntimeError("provider unavailable")
        return {"content": "ok"}


def test_observer_groups_successful_calls_by_stage() -> None:
    token = start_llm_metrics()
    try:
        ObservedLLM(StubLLM(), "intent_classifier").chat([])
        ObservedLLM(StubLLM(), "agent_runtime").chat([])
        ObservedLLM(StubLLM(), "agent_runtime").chat([])
        metrics = snapshot_llm_metrics()
    finally:
        clear_llm_metrics(token)

    assert metrics["call_count"] == 3
    assert metrics["success_count"] == 3
    assert metrics["by_stage"]["intent_classifier"]["call_count"] == 1
    assert metrics["by_stage"]["agent_runtime"]["call_count"] == 2
    assert metrics["total_ms"] >= 0


def test_observer_records_failure_without_swallowing_exception() -> None:
    token = start_llm_metrics()
    try:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            ObservedLLM(StubLLM(fail=True), "clarifier").chat([])
        metrics = snapshot_llm_metrics()
    finally:
        clear_llm_metrics(token)

    assert metrics["failure_count"] == 1
    assert metrics["by_stage"]["clarifier"]["failure_count"] == 1


def test_metrics_are_empty_outside_request_context() -> None:
    assert snapshot_llm_metrics()["call_count"] == 0
