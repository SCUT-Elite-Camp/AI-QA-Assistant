# CP2 IntentClassifier Contract

## Status

`QueryIntent` is a frozen public enum.

`IntentClassifier` and `IntentResult` are internal Query Understanding
components. Agent Runner should consume `QueryPlan`, not `IntentResult`
directly.

## Purpose

`IntentClassifier` classifies a user query into the frozen CP2 intent taxonomy
and identifies whether the query appears to be a follow-up or a reply to a
clarification question.

## Interface

```python
from agent.query import IntentClassifier, IntentResult

result = IntentClassifier().classify(
    query="Compare CP1 and CP2.",
    history=[],
)
```

Result:

```python
IntentResult(
    intent=QueryIntent.COMPARISON,
    confidence=0.97,
    is_follow_up=False,
    is_clarification_reply=False,
    reason="The user explicitly requests a comparison.",
)
```

## IntentResult

```python
class IntentResult(BaseModel):
    intent: QueryIntent
    confidence: float
    is_follow_up: bool = False
    is_clarification_reply: bool = False
    reason: str = ""
```

Validation rules:

- `intent` must be a member of the frozen `QueryIntent` enum.
- `confidence` must be between zero and one.
- unknown fields are rejected;
- `reason` is internal diagnostic text and is not shown directly to the user.

## Classification Rules

| Intent | Classification rule |
|---|---|
| `knowledge_qa` | Requests a factual answer from knowledge sources |
| `document_search` | Requests documents, document identities, or a document list |
| `summarization` | Requests a summary of provided or retrievable material |
| `comparison` | Requests comparison of two or more objects |
| `casual_chat` | Ordinary conversation that does not require retrieval |
| `system_help` | Asks about this system's real capabilities or usage |
| `unsupported` | Requests an action outside current system capabilities |

The model must choose exactly one intent and must not invent additional intent
names.

## History Handling

Only messages with:

- role `user` or `assistant`; and
- string `content`

are included in the classification prompt.

Tool messages and malformed history entries are excluded.

## Follow-up Flags

`is_follow_up` indicates that the current query depends on prior conversation.

`is_clarification_reply` is currently a semantic hint inferred from history.
It is not authoritative. Future Query Understanding must verify this flag
against persistent pending-clarification state before writing it to
`QueryPlan`.

## Safe Fallback

The classifier falls back when:

- the LLM call fails;
- response content is empty;
- JSON is invalid;
- the intent name is unknown;
- confidence is missing or outside zero to one;
- required fields are missing;
- unknown fields indicate contract drift.

Fallback result:

```python
IntentResult(
    intent=QueryIntent.KNOWLEDGE_QA,
    confidence=0.0,
    is_follow_up=False,
    is_clarification_reply=False,
    reason="intent_classification_failed",
)
```

This fallback is a routing default, not permission to bypass Evidence Gate,
tool allowlists, or execution budgets.

## Configuration

```env
QUERY_UNDERSTANDING_ENABLED=true
```

When disabled, the classifier does not call the LLM and returns the safe
fallback with reason `query_understanding_disabled`.

## Future QueryPlan Mapping

```text
IntentResult.intent
    → QueryPlan.intent

IntentResult.confidence
    → QueryPlan.intent_confidence

IntentResult.is_follow_up
    → QueryPlan.is_follow_up

verified clarification state
    → QueryPlan.is_clarification_reply
```

This mapping will be implemented by the future Query Understanding component.
