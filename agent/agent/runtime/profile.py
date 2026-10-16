"""Resolve public execution preferences into a small internal strategy contract."""

from dataclasses import dataclass
from enum import StrEnum


class ExecutionMode(StrEnum):
    FAST = "fast"
    THINKING = "thinking"


@dataclass(frozen=True)
class ExecutionProfile:
    requested_mode: str
    mode: ExecutionMode
    exploration_mode: str
    reason: str


class ExecutionProfileResolver:
    """Map the explicit mode; auto is a compatibility alias for Thinking."""

    def resolve(
        self,
        requested_mode: str | None,
        *,
        exploration_mode: str,
    ) -> ExecutionProfile:
        requested = (requested_mode or "fast").strip().lower()
        if requested not in {"fast", "thinking", "auto"}:
            requested = "thinking"

        if requested == "fast":
            return ExecutionProfile(requested, ExecutionMode.FAST, "off", "explicit_fast")
        return ExecutionProfile(requested, ExecutionMode.THINKING, exploration_mode,
                                "auto_alias_thinking" if requested == "auto" else "explicit_thinking")
