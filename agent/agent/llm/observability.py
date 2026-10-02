import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from agent.llm.base import BaseLLM


@dataclass
class LLMCallMetric:
    stage: str
    elapsed_ms: float
    success: bool


@dataclass
class LLMCallMetrics:
    calls: list[LLMCallMetric] = field(default_factory=list)

    def record(self, stage: str, elapsed_ms: float, success: bool) -> None:
        self.calls.append(LLMCallMetric(stage, round(elapsed_ms, 2), success))

    def snapshot(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, int | float]] = {}
        for call in self.calls:
            stage = by_stage.setdefault(
                call.stage,
                {"call_count": 0, "success_count": 0, "failure_count": 0, "total_ms": 0.0},
            )
            stage["call_count"] += 1
            stage["success_count"] += int(call.success)
            stage["failure_count"] += int(not call.success)
            stage["total_ms"] = round(float(stage["total_ms"]) + call.elapsed_ms, 2)
        return {
            "call_count": len(self.calls),
            "success_count": sum(call.success for call in self.calls),
            "failure_count": sum(not call.success for call in self.calls),
            "total_ms": round(sum(call.elapsed_ms for call in self.calls), 2),
            "by_stage": by_stage,
        }


_CURRENT_METRICS: ContextVar[LLMCallMetrics | None] = ContextVar(
    "agent_llm_call_metrics",
    default=None,
)


def start_llm_metrics() -> Token:
    return _CURRENT_METRICS.set(LLMCallMetrics())


def snapshot_llm_metrics() -> dict[str, Any]:
    metrics = _CURRENT_METRICS.get()
    return metrics.snapshot() if metrics is not None else LLMCallMetrics().snapshot()


def clear_llm_metrics(token: Token) -> None:
    _CURRENT_METRICS.reset(token)


class ObservedLLM(BaseLLM):
    """Record request-local latency without logging prompts or credentials."""

    def __init__(self, llm: BaseLLM, stage: str) -> None:
        self.llm = llm
        self.stage = stage

    def generate(self, prompt: str) -> str:
        started = time.perf_counter()
        success = False
        try:
            result = self.llm.generate(prompt)
            success = True
            return result
        finally:
            self._record(started, success)

    def chat(self, messages: list[dict], tools: list[dict] = None, **kwargs) -> dict:
        started = time.perf_counter()
        success = False
        try:
            result = self.llm.chat(messages, tools=tools, **kwargs)
            success = True
            return result
        finally:
            self._record(started, success)

    def _record(self, started: float, success: bool) -> None:
        metrics = _CURRENT_METRICS.get()
        if metrics is not None:
            metrics.record(
                self.stage,
                (time.perf_counter() - started) * 1000,
                success,
            )
