from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from deep_research.runtime import ResearchGraphRuntime, ResearchRuntimeTimeout


class _Repository:
    def __init__(self, *, elapsed_seconds: int, budget_seconds: int) -> None:
        self.job = SimpleNamespace(
            plan_version=1,
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=elapsed_seconds),
        )
        self.plan = SimpleNamespace(
            budget=SimpleNamespace(max_runtime_seconds=budget_seconds)
        )

    def get_job(self, research_id: str):
        return self.job

    def get_plan(self, research_id: str, version: int):
        return self.plan


def test_runtime_budget_rejects_an_overdue_stage() -> None:
    runtime = ResearchGraphRuntime.__new__(ResearchGraphRuntime)
    runtime.repository = _Repository(elapsed_seconds=31, budget_seconds=30)
    runtime.control_plane = SimpleNamespace(authorize_job=lambda *args: None, get_manifest=lambda *args: None)

    with pytest.raises(ResearchRuntimeTimeout, match="research_runtime_budget_exceeded"):
        runtime._assert_runtime_budget("research-overdue")


def test_runtime_budget_allows_a_stage_with_time_remaining() -> None:
    runtime = ResearchGraphRuntime.__new__(ResearchGraphRuntime)
    runtime.repository = _Repository(elapsed_seconds=5, budget_seconds=30)
    runtime.control_plane = SimpleNamespace(authorize_job=lambda *args: None, get_manifest=lambda *args: None)

    runtime._assert_runtime_budget("research-active")
