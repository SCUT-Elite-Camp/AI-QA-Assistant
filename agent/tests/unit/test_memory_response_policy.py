import pytest

from agent.config.settings import settings
from agent.memory.memory_response_policy import MemoryResponsePolicy
from agent.memory.persistent_models import PersistentFact


@pytest.fixture(autouse=True)
def _enable_session_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SESSION_FACT_ENABLED", True)


@pytest.mark.parametrize(
    "query",
    [
        "我记住了什么？",
        "我之前确认的记忆是什么？",
        "what have you remembered?",
        "WHAT ARE MY CONFIRMED MEMORIES?",
    ],
)
def test_exact_recall_returns_visible_facts_in_bff_order(query: str) -> None:
    policy = MemoryResponsePolicy(now_ms=lambda: 1000)

    recall = policy.resolve(
        query,
        [
            PersistentFact(id="goal", category="GOAL", value="完成答辩准备。"),
            PersistentFact(id="preference", category="PREFERENCE", value="使用中文。"),
            PersistentFact(
                id="expired",
                category="GOAL",
                value="不应出现。",
                expires_at=1000,
            ),
        ],
    )

    assert recall.handled is True
    assert recall.answer == "已确认的记忆：\n- GOAL: 完成答辩准备。\n- PREFERENCE: 使用中文。"


def test_exact_recall_reports_no_visible_confirmed_fact_without_model_guessing() -> None:
    recall = MemoryResponsePolicy().resolve("我记住了什么？", [])

    assert recall.handled is True
    assert recall.answer == "当前没有可见且未过期的已确认记忆。"


def test_non_exact_question_does_not_trigger_memory_recall() -> None:
    recall = MemoryResponsePolicy().resolve(
        "我之前确认的目标是什么？",
        [PersistentFact(id="goal", category="GOAL", value="不应自动回答。")],
    )

    assert recall.handled is False
    assert recall.answer is None


def test_session_fact_gate_closed_does_not_bypass_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SESSION_FACT_ENABLED", False)

    recall = MemoryResponsePolicy().resolve(
        "我记住了什么？",
        [PersistentFact(id="goal", category="GOAL", value="不应暴露。")],
    )

    assert recall.handled is False
    assert recall.answer is None
