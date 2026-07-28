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
        └── sufficient context → QueryRewriter → QueryPlanner
        ↓
QueryPlan
```

## Ownership Boundaries

- It reads history but never writes ConversationMemory.
- It creates no tools and executes no tools.
- It returns only `QueryPlan`; internal component result types are not public
  Runner inputs.
- `original_query` preserves the exact `ChatRequest.query`.
- QueryPlanner generates at most four normalized, unique sub-queries. Comparison
  queries normally produce one self-contained query per target.
- Semantic filters are restricted to Toolset-supported keys: `doc_id`,
  `doc_ids`, `space`, and `doc_type`.
- Request filters are copied, never mutated in place, and override semantic
  filters with the same key because caller-provided constraints are authoritative.
- Clarification short-circuits both rewriting and planning.

## Failure Behavior

IntentClassifier, Clarifier, and QueryRewriter each provide their own safe
fallback. QueryPlanner falls back to empty sub-queries and filters, so retrieval
can still use `standalone_query`. QueryUnderstanding validates the combined result through the
canonical `agent.schemas.query_plan.QueryPlan` model.
