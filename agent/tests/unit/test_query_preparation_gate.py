import pytest

from agent.query.preparation_gate import QueryPreparationGate
from agent.query.schemas import IntentResult
from agent.schemas.query_plan import QueryIntent


pytestmark = pytest.mark.no_storage


def _intent(
    value: QueryIntent = QueryIntent.KNOWLEDGE_QA,
    *,
    is_follow_up: bool = False,
) -> IntentResult:
    return IntentResult(
        intent=value,
        confidence=0.95,
        is_follow_up=is_follow_up,
    )


@pytest.mark.parametrize(
    "query",
    [
        "Which system layer owns the ToolRegistry?",
        "Which identifiers does Evidence Gate use to deduplicate evidence?",
        "How many Corrective Retrieval attempts are allowed per request?",
    ],
)
def test_gate_bypasses_clear_single_target_knowledge_questions(query: str) -> None:
    assert QueryPreparationGate.can_bypass(query, [], _intent()) is True


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Compare CP1 and CP2.", QueryIntent.COMPARISON),
        ("Summarize the CP2 architecture.", QueryIntent.SUMMARIZATION),
        ("Find the QueryPlan contract.", QueryIntent.DOCUMENT_SEARCH),
        (
            "What does QueryPlan contain, and why does AgentRunner consume it?",
            QueryIntent.KNOWLEDGE_QA,
        ),
        ("What does it store?", QueryIntent.KNOWLEDGE_QA),
    ],
)
def test_gate_keeps_semantically_risky_queries_on_preparation_path(
    query: str,
    intent: QueryIntent,
) -> None:
    assert QueryPreparationGate.can_bypass(query, [], _intent(intent)) is False


def test_gate_keeps_follow_up_or_history_on_preparation_path() -> None:
    history = [{"role": "user", "content": "Explain ConversationMemory."}]

    assert QueryPreparationGate.can_bypass(
        "Which fields does it store?", history, _intent(is_follow_up=True)
    ) is False


def test_gate_rejects_unreliable_or_non_english_text() -> None:
    assert QueryPreparationGate.can_bypass("��������", [], _intent()) is False
