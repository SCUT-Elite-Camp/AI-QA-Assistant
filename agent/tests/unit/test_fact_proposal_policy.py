from __future__ import annotations

import pytest

from agent.config.settings import Settings
from agent.memory.fact_proposal_policy import FactProposalPolicy


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("记住目标：完成答辩", "GOAL"),
        ("请记住目标：完成答辩", "GOAL"),
        ("REMEMBER GOAL: finish the defense", "GOAL"),
        ("记住偏好：使用中文", "PREFERENCE"),
        ("请记住偏好：使用中文", "PREFERENCE"),
        ("remember preference: use Chinese", "PREFERENCE"),
        ("记住计划约束：周五前完成", "PLAN_CONSTRAINT"),
        ("请记住计划约束：周五前完成", "PLAN_CONSTRAINT"),
        ("remember plan constraint: finish by Friday", "PLAN_CONSTRAINT"),
    ],
)
def test_every_explicit_command_produces_one_normalized_candidate(
    query: str,
    category: str,
) -> None:
    proposals = FactProposalPolicy().propose(
        query,
        actor_authenticated=True,
        current_message_id="persisted-message",
        persistent_memory_enabled=True,
        session_fact_enabled=True,
    )

    assert len(proposals) == 1
    assert proposals[0].category == category
    assert proposals[0].source_message_id == "persisted-message"
    assert proposals[0].expires_at is None


def test_parser_accepts_full_width_colon_and_normalizes_nfc_and_whitespace() -> None:
    proposals = FactProposalPolicy().propose(
        "remember preference： cafe\u0301\n  with   concise  replies ",
        actor_authenticated=True,
        current_message_id="persisted-message",
        persistent_memory_enabled=True,
        session_fact_enabled=True,
    )

    assert proposals[0].value == "café with concise replies"


def test_session_fact_gate_defaults_closed_and_can_be_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.delenv("SESSION_FACT_ENABLED", raising=False)
    assert Settings().SESSION_FACT_ENABLED is False

    monkeypatch.setenv("SESSION_FACT_ENABLED", "true")
    assert Settings().SESSION_FACT_ENABLED is True


@pytest.mark.parametrize(
    "query",
    [
        "请记住我喜欢中文。",
        "前缀 remember goal: finish",
        "remember goal:",
        "记住目标：",
        "记住目标：" + "a" * 501,
    ],
)
def test_non_commands_empty_and_too_long_values_never_propose(query: str) -> None:
    assert FactProposalPolicy().propose(
        query,
        actor_authenticated=True,
        current_message_id="persisted-message",
        persistent_memory_enabled=True,
        session_fact_enabled=True,
    ) == []


@pytest.mark.parametrize(
    ("persistent_enabled", "session_fact_enabled", "actor_authenticated"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
def test_closed_gates_or_anonymous_actor_never_propose(
    persistent_enabled: bool,
    session_fact_enabled: bool,
    actor_authenticated: bool,
) -> None:
    assert FactProposalPolicy().propose(
        "记住目标：完成答辩",
        actor_authenticated=actor_authenticated,
        current_message_id="persisted-message",
        persistent_memory_enabled=persistent_enabled,
        session_fact_enabled=session_fact_enabled,
    ) == []


def test_sensitive_value_never_proposes_or_records_a_candidate() -> None:
    assert FactProposalPolicy().propose(
        "remember goal: keep my secret token private",
        actor_authenticated=True,
        current_message_id="persisted-message",
        persistent_memory_enabled=True,
        session_fact_enabled=True,
    ) == []
