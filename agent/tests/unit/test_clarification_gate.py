from unittest.mock import Mock

import pytest

from agent.query import ClarificationDecision, ClarificationGate


pytestmark = pytest.mark.no_storage


def test_clear_query_skips_llm_clarifier() -> None:
    clarifier = Mock()
    gate = ClarificationGate(clarifier)

    result = gate.evaluate("ToolRegistry 的作用是什么？", [])

    assert result.needs_clarification is False
    assert result.reason == "deterministic_clear_query"
    clarifier.evaluate.assert_not_called()


def test_unresolved_reference_delegates_to_llm_clarifier() -> None:
    clarifier = Mock()
    clarifier.evaluate.return_value = ClarificationDecision(
        needs_clarification=True,
        question="请说明“它”指什么？",
        reason="missing reference",
    )
    gate = ClarificationGate(clarifier)

    result = gate.evaluate("它是怎么处理的？", [])

    assert result.needs_clarification is True
    clarifier.evaluate.assert_called_once()


def test_reference_with_history_continues_without_llm() -> None:
    clarifier = Mock()
    gate = ClarificationGate(clarifier)

    result = gate.evaluate(
        "它有什么作用？",
        [{"role": "user", "content": "介绍 ToolRegistry"}],
    )

    assert result.needs_clarification is False
    clarifier.evaluate.assert_not_called()
