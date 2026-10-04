from typing import Any

from agent.answer.generator import AnswerGenerator
from agent.evidence import EvidenceGate
from agent.retrieval import CorrectiveRetrievalPlanner
from agent.runtime import FastLoop, StopReason
from agent.runtime.support import RuntimeSupport
from agent.schemas.intent_policy import IntentPolicy
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.schemas.tool_execution import Evidence, ToolExecutionResult


class FakeLLM:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response or {"role": "assistant", "content": "Answer [1]"}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self.error:
            raise self.error
        return self.response


class FakeExecutor:
    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        score = self.scores.pop(0)
        evidence = Evidence(
            doc_id="doc-1", chunk_id=f"doc-1::{len(self.calls)}", chunk_index=0,
            title="Doc", content="grounded content", score=score,
            retrieval_query=kwargs["arguments"]["query"],
            retrieval_mode=kwargs["arguments"]["mode"],
            retrieval_attempt=kwargs["retrieval_attempt"],
        )
        return ToolExecutionResult(
            tool_call_id=kwargs["tool_call_id"],
            tool_name=kwargs["tool_name"], success=True, evidence=[evidence],
        )


def _loop(fast_llm: FakeLLM, complex_llm: FakeLLM | None = None):
    complex_llm = complex_llm or FakeLLM()
    generator = AnswerGenerator(complex_llm=complex_llm, fast_llm=fast_llm)
    return FastLoop(answer_generator=generator, runtime_support=RuntimeSupport())


def _plan() -> QueryPlan:
    return QueryPlan(
        original_query="question", standalone_query="question",
        intent=QueryIntent.KNOWLEDGE_QA,
    )


def test_fast_loop_does_not_retrieve_when_tool_call_budget_is_zero() -> None:
    executor = FakeExecutor([0.9])
    result = _loop(FakeLLM()).run(
        _plan(), policy=IntentPolicy(
            candidate_tools=("search_documents",), max_tool_calls=0,
        ), tool_executor=executor, evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )

    assert result.stop_reason is StopReason.POLICY_LIMIT
    assert result.error_code == "max_tool_calls"
    assert not result.tool_calls
    assert not executor.calls


def test_fast_loop_retrieves_directly_without_tool_selection_and_answers_from_evidence() -> None:
    fast_llm = FakeLLM()
    executor = FakeExecutor([0.9])
    result = _loop(fast_llm).run(
        _plan(), policy=IntentPolicy(candidate_tools=("search_documents",)),
        tool_executor=executor, evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )
    assert result.stop_reason is StopReason.FINAL_ANSWER
    assert result.evidence
    assert result.evidence_gate_reason == "evidence_accepted"
    assert result.covered_evidence_targets == ["question"]
    assert result.missing_evidence_targets == []
    assert result.eligible_evidence_count == 1
    assert result.rejected_evidence_count == 0
    assert len(executor.calls) == 1
    assert fast_llm.calls[0]["tools"] is None
    assert "AUTHORITATIVE_EVIDENCE" in fast_llm.calls[0]["messages"][-1]["content"]


def test_fast_loop_allows_only_one_corrective_retrieval() -> None:
    executor = FakeExecutor([0.1, 0.9])
    result = _loop(FakeLLM()).run(
        _plan(), policy=IntentPolicy(
            candidate_tools=("search_documents",), max_retrieval_attempts=2,
        ), tool_executor=executor, evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )
    assert result.stop_reason is StopReason.FINAL_ANSWER
    assert len(executor.calls) == 2
    assert result.retrieval_attempts == 2
    assert result.evidence_gate_reason == "evidence_accepted"
    assert result.covered_evidence_targets == ["question"]
    assert result.missing_evidence_targets == []
    assert result.eligible_evidence_count == 1
    assert result.rejected_evidence_count == 1


def test_fast_loop_tool_budget_blocks_corrective_retrieval() -> None:
    executor = FakeExecutor([0.1, 0.9])
    result = _loop(FakeLLM()).run(
        _plan(), policy=IntentPolicy(
            candidate_tools=("search_documents",), max_tool_calls=1,
            max_retrieval_attempts=2,
        ), tool_executor=executor, evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )

    assert result.stop_reason is StopReason.POLICY_LIMIT
    assert result.error_code == "max_tool_calls"
    assert len(executor.calls) == 1
    assert len(result.tool_calls) == 1
    assert result.retrieval_attempts == 1
    assert result.evidence_gate_reason == "no_valid_evidence"
    assert result.eligible_evidence_count == 0
    assert result.rejected_evidence_count == 1


def test_fast_loop_returns_no_context_after_bounded_retry_is_insufficient() -> None:
    executor = FakeExecutor([0.1, 0.2])
    result = _loop(FakeLLM()).run(
        _plan(), policy=IntentPolicy(
            candidate_tools=("search_documents",), max_retrieval_attempts=2,
        ), tool_executor=executor, evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )
    assert result.stop_reason is StopReason.NO_RELEVANT_CONTEXT
    assert len(executor.calls) == 2
    assert not result.answer
    assert result.evidence_gate_reason == "no_valid_evidence"
    assert result.eligible_evidence_count == 0
    assert result.rejected_evidence_count == 2
    assert all(item["score"] < 0.5 for item in result.evidence)


def test_fast_answer_model_failure_falls_back_to_complex_model() -> None:
    fast_llm = FakeLLM(error=RuntimeError("fast unavailable"))
    complex_llm = FakeLLM()
    result = _loop(fast_llm, complex_llm).run(
        _plan(), policy=IntentPolicy(candidate_tools=("search_documents",)),
        tool_executor=FakeExecutor([0.9]), evidence_gate=EvidenceGate(min_score=0.5),
        corrective_retrieval=CorrectiveRetrievalPlanner(), history=[],
        trace_id="trace", mode="hybrid", top_k=5,
    )
    assert result.stop_reason is StopReason.FINAL_ANSWER
    assert len(fast_llm.calls) == 1
    assert len(complex_llm.calls) == 1
