"""One request owns every Thinking model, tool and verification allowance."""
import json
import time
from dataclasses import dataclass, field
from agent.errors.exceptions import BudgetExceeded


@dataclass
class RunBudget:
    max_model_calls: int
    max_tool_calls: int
    max_context_chars: int
    max_reserved_tokens: int
    max_verifications: int
    timeout_seconds: float
    started: float = field(default_factory=time.monotonic)
    model_calls: int = 0
    tool_calls: int = 0
    reserved_tokens: int = 0
    verifications: int = 0

    def remaining_seconds(self) -> float:
        remaining = self.timeout_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise BudgetExceeded("thinking_deadline_exceeded")
        return remaining

    def model(self, messages: list, tools: list | None, output_tokens: int) -> None:
        self.remaining_seconds()
        serialized = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False)
        if len(serialized) > self.max_context_chars:
            raise BudgetExceeded("thinking_context_budget_exceeded")
        # Conservative UTF-8 byte accounting plus framing, not a claim of exact
        # provider tokenization. Full output allowance is reserved even on errors.
        reservation = len(serialized.encode("utf-8")) + output_tokens + 256
        if self.model_calls >= self.max_model_calls:
            raise BudgetExceeded("thinking_model_call_budget_exceeded")
        if self.reserved_tokens + reservation > self.max_reserved_tokens:
            raise BudgetExceeded("thinking_token_reservation_exceeded")
        self.model_calls += 1
        self.reserved_tokens += reservation

    def tool(self) -> None:
        self.remaining_seconds()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("thinking_tool_call_budget_exceeded")
        self.tool_calls += 1

    def verify(self) -> None:
        self.remaining_seconds()
        if self.verifications >= self.max_verifications:
            raise BudgetExceeded("thinking_verification_budget_exceeded")
        self.verifications += 1

    def snapshot(self) -> dict:
        return {"model_calls": self.model_calls, "tool_calls": self.tool_calls,
                "reserved_tokens": self.reserved_tokens, "verifications": self.verifications,
                "elapsed_seconds": round(time.monotonic() - self.started, 3)}
