# CP2 QueryRewriter Contract

## Purpose

`QueryRewriter` combines the current user query with conversation history to
produce a standalone query suitable for knowledge retrieval.

Rewriting affects retrieval only. The final answer must still address the
user's original query.

## Interface

```python
from agent.query import QueryRewriter, RewriteResult

result = QueryRewriter().rewrite(
    query="What are its limitations?",
    history=[
        {"role": "user", "content": "Describe the Agent Q1 deliverables."},
        {"role": "assistant", "content": "Q1 implemented a single-turn RAG flow."},
    ],
)
```

Result:

```python
RewriteResult(
    original_query="What are its limitations?",
    rewritten_query="What are the limitations of the Agent Q1 implementation?",
    changed=True,
    reason="Resolved the pronoun using conversation history.",
)
```

## Behavioral Rules

- Do not change the user's intent.
- Do not introduce facts that are absent from the conversation.
- Preserve module names, interface names, code identifiers, and technical
  terminology.
- Keep the original query when it is already clear.
- `original_query` is populated by application code, not trusted from model
  output.
- Only string messages with `user` or `assistant` roles are included in
  history.
- Fall back to the original query when the model fails, returns invalid JSON,
  returns an empty query, or fails schema validation.

## Configuration

```env
QUERY_REWRITE_ENABLED=true
```

When disabled, the component does not call the model and returns the original
query.

## Recommended Integration Order

```text
Load conversation history by session_id
    ↓
Evaluate clarification
    ↓
QueryRewriter.rewrite(query, history)
    ↓
Pass rewritten_query to retrieval
    ↓
Generate the final answer for original_query
```

The current implementation is an internal Query Understanding component. It
will eventually populate `QueryPlan.standalone_query`; it is not intended to
remain a separate input to Agent Runner.
