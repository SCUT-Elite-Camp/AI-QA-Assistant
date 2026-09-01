import json

import pytest

from agent.answer import AnswerCompletenessChecker
from agent.answer.schemas import AnswerCompletenessResult
from agent.runtime.runner import AgentRunner
from agent.runtime.state import AgentState
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence
from agent.service.audit_service import AuditService
from toolset.tool_layer import ToolRegistry


pytestmark = pytest.mark.no_storage


class ScriptedLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def _plan() -> QueryPlan:
    return QueryPlan(
        original_query="Who were Boeing's customers and what was the government share?",
        standalone_query="Boeing customers and US government revenue share in 2022",
        sub_queries=["Boeing customer types", "US government revenue share"],
    )


def _single_target_plan() -> QueryPlan:
    return QueryPlan(
        original_query="What is CP2?",
        standalone_query="What is CP2?",
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


def test_multi_aspect_flow_requires_semantic_check_without_sub_queries() -> None:
    plan = QueryPlan(
        original_query="请求从进入系统到返回答案会经过哪些核心步骤？",
        standalone_query="请求从进入系统到返回答案会经过哪些核心步骤？",
    )

    assert AnswerCompletenessChecker.requires_llm_check(plan) is True


def test_complete_answer_does_not_require_repair() -> None:
    llm = ScriptedLLM(
        [{"content": json.dumps({
            "complete": True,
            "missing_aspects": [],
            "missing_critical_facts": [],
            "reason": "All requested facts are covered.",
            "check_performed": True,
        })}]
    )
    checker = AnswerCompletenessChecker(llm)

    result = checker.check(_plan(), "Airlines were customers; the share was 40% [1].", _evidence())

    assert result.complete is True
    assert len(llm.calls) == 1


def test_missing_numeric_fact_is_passed_to_single_repair_call() -> None:
    llm = ScriptedLLM(
        [
            {"content": "```json\n" + json.dumps({
                "complete": False,
                "missing_aspects": ["US government revenue share"],
                "missing_critical_facts": ["The U.S. government accounted for 40% of revenue."],
                "reason": "The answer omits a material percentage.",
                "check_performed": True,
            }) + "\n```"},
            {"content": "Airlines were customers, and the U.S. government represented 40% of revenue [1]."},
        ]
    )
    checker = AnswerCompletenessChecker(llm)

    result = checker.check(_plan(), "Commercial airlines were customers [1].", _evidence())
    repaired = checker.repair(
        _plan(), "Commercial airlines were customers [1].", _evidence(), result
    )

    assert result.complete is False
    assert "40%" in result.missing_critical_facts[0]
    assert "40%" in repaired
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[1]["messages"][0]["content"]
    assert "using only the supplied evidence" in repair_prompt
    assert "exactly once" in repair_prompt


def test_empty_evidence_skips_llm_check() -> None:
    llm = ScriptedLLM([])
    result = AnswerCompletenessChecker(llm).check(_plan(), "An answer", [])

    assert result.complete is True
    assert result.check_performed is False
    assert llm.calls == []


def test_single_target_answer_uses_deterministic_check() -> None:
    llm = ScriptedLLM([])

    result = AnswerCompletenessChecker(llm).check(
        _single_target_plan(),
        "CP2 is an evidence-constrained agent workflow [1].",
        _evidence(),
    )

    assert result.complete is True
    assert result.reason == "deterministic_single_target_check_passed"
    assert result.check_performed is True
    assert llm.calls == []


def test_single_target_answer_without_valid_citation_requests_repair() -> None:
    llm = ScriptedLLM([])

    result = AnswerCompletenessChecker(llm).check(
        _single_target_plan(),
        "CP2 is an evidence-constrained agent workflow [2].",
        _evidence(),
    )

    assert result.complete is False
    assert result.missing_aspects == ["citation_to_accepted_evidence"]
    assert result.reason == "deterministic_check_missing_valid_citation"
    assert llm.calls == []


class RecordingChecker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.check_calls = 0
        self.repair_calls = 0

    def check(self, query_plan, answer, evidence):
        self.check_calls += 1
        if self.fail:
            raise ValueError("invalid checker response")
        return AnswerCompletenessResult(
            complete=False,
            missing_aspects=["US government revenue share"],
            missing_critical_facts=["40% of revenue"],
            reason="missing percentage",
        )

    def repair(self, query_plan, answer, evidence, result):
        self.repair_calls += 1
        return "Commercial airlines were customers; the government share was 40% [1]."


def _state() -> AgentState:
    return AgentState(
        trace_id="trace-completeness",
        query_plan=_plan(),
        evidence=[item.model_dump() for item in _evidence()],
    )


def test_runner_performs_at_most_one_repair_using_existing_evidence() -> None:
    checker = RecordingChecker()
    runner = AgentRunner(
        llm=ScriptedLLM([]),
        registry=ToolRegistry(tools=[]),
        audit_service=AuditService(),
        answer_completeness_checker=checker,
    )
    state = _state()

    answer = runner._check_and_repair_answer(
        state=state,
        policy=IntentPolicy(requires_citations=True),
        answer="Commercial airlines were customers [1].",
    )

    assert "40%" in answer
    assert checker.check_calls == 1
    assert checker.repair_calls == 1
    assert state.answer_repair_attempted is True
    assert state.retrieval_attempts == 0
    assert state.tool_calls == []


def test_checker_failure_preserves_original_answer() -> None:
    checker = RecordingChecker(fail=True)
    runner = AgentRunner(
        llm=ScriptedLLM([]),
        registry=ToolRegistry(tools=[]),
        audit_service=AuditService(),
        answer_completeness_checker=checker,
    )
    state = _state()

    answer = runner._check_and_repair_answer(
        state=state,
        policy=IntentPolicy(requires_citations=True),
        answer="Original answer [1].",
    )

    assert answer == "Original answer [1]."
    assert checker.check_calls == 1
    assert checker.repair_calls == 0
    assert state.answer_repair_attempted is False
