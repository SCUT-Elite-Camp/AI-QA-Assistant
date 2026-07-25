# CP2 QueryIntent and QueryPlan Contract

## 1. Scope

This document freezes only these public schemas:

- `QueryIntent`
- `QueryPlan`

It does not define the implementation of IntentClassifier, Query
Understanding, PolicyRouter, or Agent Runner.

## 2. Data Flow

```text
User query + conversation history
        ↓
Query Understanding
        ↓
QueryPlan
        ↓
IntentPolicy / Agent Runner
```

Producer:

- Query Understanding

Consumers:

- PolicyRouter
- Agent Runner
- structured execution logs and RunSummary

## 3. QueryIntent

```python
class QueryIntent(StrEnum):
    KNOWLEDGE_QA = "knowledge_qa"
    DOCUMENT_SEARCH = "document_search"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    CASUAL_CHAT = "casual_chat"
    SYSTEM_HELP = "system_help"
    UNSUPPORTED = "unsupported"
```

`QueryIntent` represents the result of intent classification. It does not
perform classification.

| Intent | Meaning |
|---|---|
| `knowledge_qa` | Answer a question using knowledge evidence |
| `document_search` | Find documents or return a document list |
| `summarization` | Summarize one or more sources |
| `comparison` | Compare two or more objects |
| `casual_chat` | Respond without knowledge retrieval |
| `system_help` | Explain system capabilities or usage |
| `unsupported` | Reject a request outside current capabilities |

The model must not invent intent names outside this enum.

## 4. QueryPlan

```python
class QueryPlan(BaseModel):
    original_query: str
    standalone_query: str

    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA
    intent_confidence: float = 1.0

    is_follow_up: bool = False
    is_clarification_reply: bool = False

    needs_clarification: bool = False
    clarification_question: str = ""
    ambiguity_reason: str = ""

    sub_queries: list[str] = []
    filters: dict[str, Any] = {}
```

The implementation uses `default_factory` for `sub_queries` and `filters`, so
mutable state is never shared between requests.

## 5. Field Semantics

### original_query

The exact query submitted by the user in the current turn.

- Used to generate the final answer.
- Saved to ConversationMemory.
- Included in audit records.
- Must not be replaced with the rewritten query.

### standalone_query

A context-resolved query that can be understood without conversation history.

- Used for retrieval and tool calls.
- Leading and trailing whitespace is removed.
- Falls back to the original query when rewriting fails.

### intent

The classified user intent. If Query Understanding cannot classify safely, it
falls back to:

```python
QueryIntent.KNOWLEDGE_QA
```

### intent_confidence

Classification confidence:

```text
0.0 <= intent_confidence <= 1.0
```

Confidence may inform policy and logging, but must never allow the model to
bypass hard policy limits.

### is_follow_up

Whether the current query depends on prior conversation.

### is_clarification_reply

Whether the current message answers a clarification question from the previous
turn.

### needs_clarification

Whether the system must ask the user for missing information before execution.

When `true`:

- `clarification_question` must be non-empty;
- retrieval tools must not be called;
- normal Agent Runner execution must not start.

### clarification_question

One specific question shown to the user. It is normalized to an empty string
when `needs_clarification` is `false`.

### ambiguity_reason

An internal explanation for logs and debugging. It is not directly shown to
the user.

### sub_queries

Sub-queries created for complex tasks, such as the two sides of a comparison.
Empty sub-queries are removed.

### filters

Structured retrieval constraints extracted from the request and conversation.
Hard user constraints must not be silently removed during corrective
retrieval.

## 6. Examples

### Knowledge QA

```python
QueryPlan(
    original_query="What is the goal of CP2?",
    standalone_query="What is the goal of Agent CP2?",
    intent=QueryIntent.KNOWLEDGE_QA,
    intent_confidence=0.96,
)
```

### Follow-up

```python
QueryPlan(
    original_query="What are its limitations?",
    standalone_query="What are the limitations of the Agent CP1 implementation?",
    intent=QueryIntent.KNOWLEDGE_QA,
    intent_confidence=0.94,
    is_follow_up=True,
)
```

### Ambiguous Comparison

```python
QueryPlan(
    original_query="Compare them for me.",
    standalone_query="Compare them for me.",
    intent=QueryIntent.COMPARISON,
    intent_confidence=0.91,
    needs_clarification=True,
    clarification_question="Which objects should be compared?",
    ambiguity_reason="Comparison objects are missing.",
)
```

### Explicit Comparison

```python
QueryPlan(
    original_query="Compare CP1 and CP2.",
    standalone_query="Compare Agent CP1 and CP2.",
    intent=QueryIntent.COMPARISON,
    intent_confidence=0.98,
    sub_queries=[
        "Agent CP1 goals and implementation",
        "Agent CP2 goals and implementation",
    ],
)
```

## 7. Validation Rules

- `original_query` must not be empty or whitespace-only.
- `standalone_query` must not be empty or whitespace-only.
- `intent_confidence` must be between zero and one.
- A clarification question is required when
  `needs_clarification=true`.
- An unused clarification question is cleared when
  `needs_clarification=false`.
- Unknown fields are rejected to prevent silent contract drift.
- JSON serialization represents the intent as a string such as
  `"comparison"`.

## 8. Team Confirmation Checklist

- [ ] Query Understanding returns only the intents defined here.
- [ ] Agent Runner uses `standalone_query` for retrieval.
- [ ] Final answer generation and Memory use `original_query`.
- [ ] No tools are called when `needs_clarification=true`.
- [ ] PolicyRouter does not modify user facts stored in QueryPlan.
- [ ] Schema changes require a document update and team review.
