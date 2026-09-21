"""Coverage guard: worse repairs must roll back to the original answer."""

import pytest

from agent.answer.schemas import AnswerCompletenessResult
from agent.runtime.runner import AgentRunner
from agent.runtime.state import AgentState
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence
from agent.service.audit_service import AuditService
from toolset.tool_layer import ToolRegistry

pytestmark = pytest.mark.no_storage

ORIGINAL = "Commercial airlines were customers; the government share was 40% [1]."
WORSE = "Commercial airlines were customers [1]."
BETTER = (
    "Commercial airlines were customers; the government share was 40% [1]. "
    "Defense remained a material customer segment."
)


class ScriptedChecker:
    def __init__(self, repair_text: str) -> None:
        self.repair_text = repair_text
        self.check_calls = 0
        self.repair_calls = 0

    def check(self, query_plan, answer, evidence) -> AnswerCompletenessResult:
        self.check_calls += 1
        return AnswerCompletenessResult(
            complete=False,
            missing_aspects=["US government revenue share"],
            missing_critical_facts=["40% of revenue"],
            reason="missing percentage",
            check_performed=True,
            required_targets=["40%", "government"],
            coverage=0.5,
        )

    def repair(self, query_plan, answer, evidence, result) -> str:
        self.repair_calls += 1
        return self.repair_text


def _plan() -> QueryPlan:
    return QueryPlan(
        original_query="Who were Boeing's customers and what was the government share?",
        standalone_query="Boeing customers and US government revenue share in 2022",
        sub_queries=["Boeing customer types", "US government revenue share"],
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            doc_id="boeing-2022",
            chunk_id="chunk-1",
            title="Boeing 2022 10-K",
            content=(
                "Commercial airline customers buy commercial aircraft. The U.S. government "
                "accounted for approximately 40% of total revenues in 2022."
            ),
            score=0.9,
            retrieval_query="Boeing customers and US government revenue share in 2022",
            retrieval_mode="hybrid",
        )
    ]


def _state() -> AgentState:
    return AgentState(
        trace_id="trace-repair-guard",
        query_plan=_plan(),
        evidence=[item.model_dump() for item in _evidence()],
    )


def _run(checker: ScriptedChecker) -> tuple[str, AgentState]:
    runner = AgentRunner(
        llm=object(),
        registry=ToolRegistry(tools=[]),
        audit_service=AuditService(),
        answer_completeness_checker=checker,
    )
    state = _state()
    answer = runner._check_and_repair_answer(
        state=state,
        policy=IntentPolicy(requires_citations=True),
        answer=ORIGINAL,
    )
    return answer, state


def test_runner_rolls_back_a_repair_that_loses_ground() -> None:
    checker = ScriptedChecker(WORSE)

    answer, state = _run(checker)

    assert answer == ORIGINAL
    assert "40%" in answer
    assert checker.repair_calls == 1
    assert state.answer_repair_attempted is True
    assert state.answer_repair_rolled_back is True
    assert state.answer_repair_guard_reason in {"coverage_dropped", "lost_numeric_atoms"}


def test_runner_rejects_an_empty_repair() -> None:
    checker = ScriptedChecker("")

    answer, state = _run(checker)

    assert answer == ORIGINAL
    assert checker.repair_calls == 1
    assert state.answer_repair_rolled_back is True
    assert state.answer_repair_guard_reason == "empty_repair"


def test_runner_keeps_a_repair_that_does_not_lose_ground() -> None:
    checker = ScriptedChecker(BETTER)

    answer, state = _run(checker)

    assert answer == BETTER
    assert state.answer_repair_rolled_back is False
    assert state.answer_repair_guard_reason == "accepted"
    assert checker.repair_calls == 1
