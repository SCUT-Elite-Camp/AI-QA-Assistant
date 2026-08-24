"""Pure, deterministic planning for post-turn Snapshot compaction."""

from __future__ import annotations

from math import ceil

from agent.config.settings import settings
from agent.memory.memory_observability import MemoryObservability
from agent.memory.sensitive_value import isSensitiveMemoryValue
from agent.schemas.chat import (
    CompactionPlan,
    CompactionPlanRequest,
    CompactionPlanResponse,
    ExpectedActiveSnapshot,
    MemoryMessage,
    NewMemorySnapshot,
    NoCompactionPlan,
)


_NEW_COVERED_MESSAGES_HEADER = "[New covered messages]"
_PREVIOUS_SUMMARY_HEADER = "[Previous summary]"
_NO_SAFE_CONTENT = "- No non-sensitive content retained."


class CompactionPlanner:
    """Build an optimistic Snapshot plan from BFF-supplied, durable messages.

    The BFF owns all reads and writes.  This planner only decides whether the
    supplied revision has enough coverable history and returns a serializable
    next-Snapshot proposal.
    """

    def __init__(
        self,
        *,
        summary_max_chars: int | None = None,
        tail_messages: int | None = None,
        min_coverable_messages: int | None = None,
        soft_token_budget: int | None = None,
        observability: MemoryObservability | None = None,
    ) -> None:
        self._summary_max_chars = (
            settings.MEMORY_SNAPSHOT_SUMMARY_MAX_CHARS
            if summary_max_chars is None
            else summary_max_chars
        )
        self._tail_messages = (
            settings.MEMORY_TAIL_MESSAGES if tail_messages is None else tail_messages
        )
        self._min_coverable_messages = (
            settings.MEMORY_COMPACTION_MIN_MESSAGES
            if min_coverable_messages is None
            else min_coverable_messages
        )
        self._soft_token_budget = (
            settings.MEMORY_COMPACTION_SOFT_TOKENS
            if soft_token_budget is None
            else soft_token_budget
        )
        self._observability = observability or MemoryObservability()
        if self._summary_max_chars < 1:
            raise ValueError("summary_max_chars must be at least 1")
        if self._tail_messages < 1:
            raise ValueError("tail_messages must be at least 1")
        if self._min_coverable_messages < 1:
            raise ValueError("min_coverable_messages must be at least 1")
        if self._soft_token_budget < 1:
            raise ValueError("soft_token_budget must be at least 1")

    def plan(self, request: CompactionPlanRequest) -> CompactionPlanResponse:
        """Return a plan without reading storage or mutating any state."""

        active_snapshot = request.active_snapshot
        snapshot_version = active_snapshot.version if active_snapshot is not None else None
        if active_snapshot is not None and active_snapshot.revision != request.revision:
            self._observability.compaction(
                outcome="conflict",
                tail_count=0,
                snapshot_version=snapshot_version,
            )
            return NoCompactionPlan(should_compact=False)

        try:
            covered_to_sequence = (
                active_snapshot.covered_to_sequence if active_snapshot is not None else 0
            )
            complete_messages = self._complete_messages(
                request.messages,
                revision=request.revision,
                covered_to_sequence=covered_to_sequence,
            )
            tail_count = min(len(complete_messages), self._tail_messages)
            if len(complete_messages) <= self._tail_messages:
                self._record("skipped", tail_count, snapshot_version)
                return NoCompactionPlan(should_compact=False)

            coverable = complete_messages[: -self._tail_messages]
            if not coverable:
                self._record("skipped", tail_count, snapshot_version)
                return NoCompactionPlan(should_compact=False)

            estimated_tokens = self._estimate_tokens(request, coverable)
            if (
                len(coverable) < self._min_coverable_messages
                and estimated_tokens <= self._soft_token_budget
            ):
                self._record("skipped", tail_count, snapshot_version)
                return NoCompactionPlan(should_compact=False)

            plan = CompactionPlan(
                should_compact=True,
                expected_active_snapshot=(
                    ExpectedActiveSnapshot(
                        id=active_snapshot.id,
                        version=active_snapshot.version,
                        revision=active_snapshot.revision,
                    )
                    if active_snapshot is not None
                    else None
                ),
                new_snapshot=NewMemorySnapshot(
                    covered_from_sequence=coverable[0].sequence,
                    covered_to_sequence=coverable[-1].sequence,
                    covered_from_message_id=coverable[0].id,
                    covered_to_message_id=coverable[-1].id,
                    summary=self._build_summary(request, coverable),
                ),
            )
            self._record("planned", tail_count, snapshot_version)
            return plan
        except Exception:
            self._record("failed", 0, snapshot_version)
            return NoCompactionPlan(should_compact=False)

    def _record(
        self,
        outcome: str,
        tail_count: int,
        snapshot_version: int | None,
    ) -> None:
        self._observability.compaction(
            outcome=outcome,  # type: ignore[arg-type]
            tail_count=tail_count,
            snapshot_version=snapshot_version,
        )

    @staticmethod
    def _complete_messages(
        messages: list[MemoryMessage],
        *,
        revision: int,
        covered_to_sequence: int,
    ) -> list[MemoryMessage]:
        eligible = [
            message
            for message in messages
            if message.revision == revision
            and message.sequence > covered_to_sequence
            and message.role in {"user", "assistant"}
        ]
        eligible.sort(key=lambda message: message.sequence)
        if eligible and eligible[-1].role == "user":
            eligible.pop()
        return eligible

    @staticmethod
    def _estimate_tokens(
        request: CompactionPlanRequest,
        coverable: list[MemoryMessage],
    ) -> int:
        previous_summary = (
            request.active_snapshot.summary if request.active_snapshot is not None else ""
        )
        character_count = len(previous_summary) + sum(
            len(message.content) for message in coverable
        )
        return ceil(character_count / 4)

    def _build_summary(
        self,
        request: CompactionPlanRequest,
        coverable: list[MemoryMessage],
    ) -> str:
        safe_lines = [
            f"- {message.role}: {message.content.strip()}"
            for message in coverable
            if message.content.strip() and not isSensitiveMemoryValue(message.content)
        ]
        new_section = "\n".join(
            [_NEW_COVERED_MESSAGES_HEADER, *(safe_lines or [_NO_SAFE_CONTENT])]
        )
        if len(new_section) >= self._summary_max_chars:
            return new_section[: self._summary_max_chars]

        previous_summary = (
            request.active_snapshot.summary.strip()
            if request.active_snapshot is not None
            else ""
        )
        if not previous_summary or isSensitiveMemoryValue(previous_summary):
            return new_section

        available_for_previous = (
            self._summary_max_chars - len(new_section) - len("\n\n")
        )
        if available_for_previous <= len(_PREVIOUS_SUMMARY_HEADER):
            return new_section

        previous_content_limit = available_for_previous - len(_PREVIOUS_SUMMARY_HEADER) - 1
        previous_section = "\n".join(
            [_PREVIOUS_SUMMARY_HEADER, previous_summary[:previous_content_limit]]
        ).rstrip()
        return f"{previous_section}\n\n{new_section}"[: self._summary_max_chars]
