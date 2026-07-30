# CP2 Clarifier Contract

## Purpose

`Clarifier` determines whether required information is missing before query
rewriting or retrieval. It should request clarification only when the user's
intent cannot be safely resolved from conversation history.

## Interface

```python
from agent.query import Clarifier, ClarificationDecision

decision = Clarifier().evaluate(
    query="What is wrong with it?",
    history=[],
)
```

Example result:

```python
ClarificationDecision(
    needs_clarification=True,
    question="Do you mean the Agent layer, the Web layer, or the whole project?",
    reason="The business object is missing.",
)
```

## Clarification Is Required When

- a reference such as “it”, “this”, or “that” cannot be resolved from history;
- the query contains an action but no subject;
- the query may refer to multiple clearly different business objects;
- retrieval requires a missing time, module, document, or scope constraint.

## Clarification Is Not Required When

- the query is short but semantically clear, such as “What is RAG?”;
- conversation history resolves the reference;
- query rewriting can safely make the query standalone;
- wording is informal but intent is unambiguous.

## Configuration

```env
CLARIFICATION_ENABLED=true
```

When disabled, the component does not call the model and allows the request to
continue.

## Failure Fallback

If the model fails, returns invalid JSON, omits required fields, or claims that
clarification is needed without returning a question, the component returns:

```python
ClarificationDecision(
    needs_clarification=False,
    question="",
    reason="clarification_check_failed",
)
```

An auxiliary decision failure must not block all requests.

## Recommended Integration Order

```text
Validate request
    ↓
Load conversation history
    ↓
Clarifier.evaluate(query, history)
    ├─ clarification required
    │    ↓
    │  return clarification_required
    │    ↓
    │  save the clarification turn
    │
    └─ no clarification required
         ↓
       QueryRewriter / Query Understanding
         ↓
       retrieval
```

When clarification is required, QueryRewriter and business tools must not be
called.

The current Clarifier is an internal Query Understanding component. Its result
will eventually populate the clarification fields of `QueryPlan`.
