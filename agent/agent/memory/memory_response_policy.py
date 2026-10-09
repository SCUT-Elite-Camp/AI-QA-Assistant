"""Deterministic handling for explicit confirmed-Fact recall requests."""

from collections.abc import Callable, Sequence

from agent.memory.fact_visibility import current_time_ms, visible_session_facts
from agent.memory.persistent_models import PersistentFact
from agent.schemas.chat import MemoryRecall


class MemoryResponsePolicy:
    """Return visible confirmed SESSION Facts without a database or model call."""

    _RECALL_MARKERS = (
        "之前确认",
        "此前确认",
        "已确认",
        "确认过",
        "我之前",
        "此前",
        "你记得",
        "已记录",
        "previously confirmed",
        "confirmed before",
        "remembered",
        "saved memory",
    )
    _CATEGORY_MARKERS = {
        "GOAL": ("目标", "goal"),
        "PREFERENCE": ("偏好", "喜好", "preference"),
        "PLAN_CONSTRAINT": (
            "计划约束",
            "计划限制",
            "计划要求",
            "计划",
            "plan constraint",
            "constraint",
        ),
    }
    _CATEGORY_LABELS = {
        "GOAL": "目标",
        "PREFERENCE": "偏好",
        "PLAN_CONSTRAINT": "计划约束",
    }

    def __init__(self, *, now_ms: Callable[[], int] | None = None) -> None:
        self._now_ms = now_ms or current_time_ms

    def resolve(
        self,
        query: str,
        facts: Sequence[PersistentFact],
        *,
        visibility_cutoff_ms: int | None = None,
    ) -> MemoryRecall:
        """Handle only explicit category recall; ordinary questions remain model-bound."""
        normalized_query = query.casefold().strip()
        requested_categories = self._requested_categories(normalized_query)
        if not requested_categories or not self._is_explicit_recall(normalized_query):
            return MemoryRecall(handled=False)

        visible_facts = visible_session_facts(
            facts,
            now_ms=self._now_ms() if visibility_cutoff_ms is None else visibility_cutoff_ms,
        )
        sections: list[str] = []
        for category in requested_categories:
            values = [fact.value.strip() for fact in visible_facts if fact.category == category]
            label = self._CATEGORY_LABELS[category]
            if values:
                sections.append(f"你此前确认的{label}：\n" + "\n".join(f"- {value}" for value in values))
            else:
                sections.append(f"当前没有可见且未过期的已确认{label}。")

        return MemoryRecall(handled=True, answer="\n\n".join(sections))

    @classmethod
    def _requested_categories(cls, query: str) -> list[str]:
        return [
            category
            for category, markers in cls._CATEGORY_MARKERS.items()
            if any(marker in query for marker in markers)
        ]

    @classmethod
    def _is_explicit_recall(cls, query: str) -> bool:
        return any(marker in query for marker in cls._RECALL_MARKERS)
