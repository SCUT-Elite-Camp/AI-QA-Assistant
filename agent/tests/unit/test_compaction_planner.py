from agent.memory.compaction_planner import CompactionPlanner, isSensitiveMemoryValue
from agent.schemas.chat import CompactionPlanRequest


def message(sequence: int, role: str = "assistant", content: str | None = None) -> dict:
    return {
        "id": f"message-{sequence}",
        "sequence": sequence,
        "revision": 1,
        "role": role,
        "content": content if content is not None else f"content-{sequence}",
    }


def request(
    messages: list[dict],
    *,
    active_snapshot: dict | None = None,
    min_coverable_messages: int = 12,
    soft_token_budget: int = 1000,
) -> CompactionPlanRequest:
    return CompactionPlanRequest(
        actor={"user_id": "user-a", "authenticated": True},
        chat_id="chat-a",
        revision=1,
        active_snapshot=active_snapshot,
        messages=messages,
        tail_size=8,
        min_coverable_messages=min_coverable_messages,
        soft_token_budget=soft_token_budget,
    )


def test_eleven_coverable_messages_do_not_create_a_snapshot() -> None:
    plan = CompactionPlanner().plan(request([message(index) for index in range(1, 20)]))

    assert plan.should_compact is False
    assert plan.new_snapshot is None


def test_twelve_coverable_messages_create_the_first_snapshot_and_keep_tail() -> None:
    plan = CompactionPlanner().plan(request([message(index) for index in range(1, 21)]))

    assert plan.should_compact is True
    assert plan.expected_active_snapshot is None
    assert plan.new_snapshot is not None
    assert plan.new_snapshot.covered_from_sequence == 1
    assert plan.new_snapshot.covered_to_sequence == 12
    assert plan.new_snapshot.covered_to_message_id == "message-12"


def test_incremental_plan_uses_old_summary_and_omits_sensitive_messages() -> None:
    plan = CompactionPlanner().plan(request(
        [message(index) for index in range(11, 31)],
        active_snapshot={
            "id": "snapshot-1",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 10,
            "summary": "Old summary.",
        },
    ))

    assert plan.should_compact is True
    assert plan.expected_active_snapshot is not None
    assert plan.expected_active_snapshot.version == 1
    assert plan.new_snapshot is not None
    assert "Old summary." in plan.new_snapshot.summary

    sensitive_plan = CompactionPlanner().plan(request(
        [
            message(11, content="safe message"),
            message(12, content="password: never retain this"),
            *[message(index) for index in range(13, 31)],
        ],
        active_snapshot={
            "id": "snapshot-1",
            "version": 1,
            "revision": 1,
            "covered_to_sequence": 10,
            "summary": "Old summary.",
        },
    ))
    assert sensitive_plan.new_snapshot is not None
    assert "password: never retain this" not in sensitive_plan.new_snapshot.summary


def test_soft_token_budget_and_unpaired_final_user_are_handled_deterministically() -> None:
    plan = CompactionPlanner().plan(request(
        [message(1, content="x" * 4004), *[message(index) for index in range(2, 10)]],
    ))
    assert plan.should_compact is True
    assert plan.new_snapshot is not None
    assert plan.new_snapshot.covered_to_sequence == 1

    unpaired = CompactionPlanner().plan(request(
        [message(index) for index in range(1, 21)] + [message(21, role="user")],
    ))
    assert unpaired.new_snapshot is not None
    assert unpaired.new_snapshot.covered_to_sequence == 12


def test_sensitive_memory_rules_match_the_frozen_contract() -> None:
    assert isSensitiveMemoryValue("API KEY: abc") is True
    assert isSensitiveMemoryValue("身份证 440524188001010014") is True
    assert isSensitiveMemoryValue("card 6222 0212 3456 7890") is True
    assert isSensitiveMemoryValue("请用简洁中文回答") is False
