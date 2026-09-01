"""Pure, deterministic post-turn Snapshot compaction planning."""

import math
import re

from agent.schemas.chat import (
    CompactionPlanRequest,
    CompactionPlanResponse,
    ExpectedActiveSnapshot,
    MemoryMessage,
    NewMemorySnapshot,
)


_SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api key",
    "private key",
    "access key",
    "银行卡",
    "银行账户",
    "账号",
    "住址",
    "详细地址",
    "诊断",
    "病历",
    "疾病",
    "药物",
    "金融账户",
)
_CHINESE_ID_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")
_NON_DIGIT_PATTERN = re.compile(r"\D+")
_SUMMARY_MAX_CHARS = 1200


def isSensitiveMemoryValue(text: str) -> bool:
    """Apply the frozen Unit 09 redaction rules without logging the value."""
    normalized = text.casefold()
    if any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS):
        return True
    if _CHINESE_ID_PATTERN.search(text):
        return True
    digit_count = len(_NON_DIGIT_PATTERN.sub("", text))
    return 13 <= digit_count <= 19


class CompactionPlanner:
    """Build an optimistic Snapshot plan from trusted, persisted messages only."""

    def plan(self, request: CompactionPlanRequest) -> CompactionPlanResponse:
        covered_to_sequence = (
            request.active_snapshot.covered_to_sequence
            if request.active_snapshot is not None
            else 0
        )
        complete_messages = self._complete_messages(request.messages, covered_to_sequence)
        if len(complete_messages) <= request.tail_size:
            return CompactionPlanResponse(should_compact=False)

        coverable = complete_messages[: -request.tail_size]
        if not coverable:
            return CompactionPlanResponse(should_compact=False)

        estimated_tokens = self._estimate_tokens(request, coverable)
        if (
            len(coverable) < request.min_coverable_messages
            and estimated_tokens <= request.soft_token_budget
        ):
            return CompactionPlanResponse(should_compact=False)

        return CompactionPlanResponse(
            should_compact=True,
            expected_active_snapshot=(
                ExpectedActiveSnapshot(
                    id=request.active_snapshot.id,
                    version=request.active_snapshot.version,
                    revision=request.active_snapshot.revision,
                )
                if request.active_snapshot is not None
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

    @staticmethod
    def _complete_messages(
        messages: list[MemoryMessage],
        covered_to_sequence: int,
    ) -> list[MemoryMessage]:
        complete_messages = [
            message
            for message in messages
            if message.sequence > covered_to_sequence
            and message.role in {"user", "assistant"}
        ]
        if complete_messages and complete_messages[-1].role == "user":
            complete_messages.pop()
        return complete_messages

    @staticmethod
    def _estimate_tokens(
        request: CompactionPlanRequest,
        coverable: list[MemoryMessage],
    ) -> int:
        old_summary = request.active_snapshot.summary if request.active_snapshot else ""
        character_count = len(old_summary) + sum(len(message.content) for message in coverable)
        return math.ceil(character_count / 4)

    @staticmethod
    def _build_summary(
        request: CompactionPlanRequest,
        coverable: list[MemoryMessage],
    ) -> str:
        sections: list[str] = []
        if request.active_snapshot and request.active_snapshot.summary.strip():
            sections.append(f"[Previous summary]\n{request.active_snapshot.summary.strip()}")

        safe_lines = [
            f"- {message.role}: {message.content.strip()}"
            for message in coverable
            if message.content.strip() and not isSensitiveMemoryValue(message.content)
        ]
        if safe_lines:
            sections.append("[New covered messages]\n" + "\n".join(safe_lines))
        elif not sections:
            sections.append("[New covered messages]\n- No non-sensitive content retained.")

        return "\n\n".join(sections)[:_SUMMARY_MAX_CHARS]
