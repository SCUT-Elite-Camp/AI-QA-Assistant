# Query Understanding

## Purpose

`QueryUnderstanding` is the single public query-analysis entry point. It
composes the internal IntentClassifier, Clarifier, and QueryRewriter components
and returns the frozen `QueryPlan` contract.

```python
plan = query_understanding.analyze(
    request.query,
    memory.get_messages(request.session_id),
    filters=request.filters,
)
```

## Execution Order

```text
query + read-only history
        ↓
IntentClassifier
        ↓
Clarifier
        ├── clarification required → keep the original query and stop rewriting
        └── sufficient context → QueryRewriter
        ↓
QueryPlan
```

## Ownership Boundaries

- It reads history but never writes ConversationMemory.
- It creates no tools and executes no tools.
- It returns only `QueryPlan`; internal component result types are not public
  Runner inputs.
- `original_query` preserves the exact `ChatRequest.query`.
- Request filters are copied into the plan and are never mutated in place.
- Sub-query generation and semantic filter extraction are not implemented in
  this first orchestration version.

## Failure Behavior

IntentClassifier, Clarifier, and QueryRewriter each provide their own safe
fallback. QueryUnderstanding validates the combined result through the
canonical `agent.schemas.query_plan.QueryPlan` model.
