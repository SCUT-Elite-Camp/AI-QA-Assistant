from agent.memory.memory_response_policy import MemoryResponsePolicy
from agent.memory.persistent_models import PersistentFact


def test_explicit_recall_returns_only_visible_requested_fact_category() -> None:
    policy = MemoryResponsePolicy(now_ms=lambda: 1000)
    recall = policy.resolve(
        "我之前确认的目标是什么？",
        [
            PersistentFact(id="goal", category="GOAL", value="完成答辩准备。"),
            PersistentFact(
                id="preference",
                category="PREFERENCE",
                value="使用中文。",
            ),
            PersistentFact(
                id="expired",
                category="GOAL",
                value="不应出现。",
                expires_at=1000,
            ),
        ],
    )

    assert recall.handled is True
    assert recall.answer == "你此前确认的目标：\n- 完成答辩准备。"


def test_explicit_recall_reports_no_visible_confirmed_fact_without_model_guessing() -> None:
    policy = MemoryResponsePolicy()
    recall = policy.resolve("我之前确认的偏好是什么？", [])

    assert recall.handled is True
    assert recall.answer == "当前没有可见且未过期的已确认偏好。"


def test_non_explicit_question_does_not_trigger_memory_recall() -> None:
    policy = MemoryResponsePolicy()
    recall = policy.resolve(
        "如何设定项目目标？",
        [PersistentFact(id="goal", category="GOAL", value="不应自动回答。")],
    )

    assert recall.handled is False
    assert recall.answer is None
