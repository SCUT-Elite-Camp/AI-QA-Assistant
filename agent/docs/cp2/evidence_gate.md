# Evidence Gate

## Purpose

Evidence Gate is a deterministic quality boundary between tool execution and
answer generation. It never calls an LLM.

```text
ToolExecutionResult.evidence
        ↓
score filter + deduplication + intent-specific rule
        ↓
accepted / corrective retrieval / no_relevant_context
```

## Common Rules

- Discard Evidence below `MIN_RETRIEVAL_SCORE`.
- Deduplicate by `doc_id + chunk_id`, keeping the highest score.
- Sort accepted Evidence by descending score.
- Only accepted Evidence may enter answer generation and Citation creation.

## Intent Rules

| Evidence policy | Acceptance rule |
|---|---|
| `none` | Evidence is not required |
| `single_fact` | At least one valid item |
| `document_identity` | At least one valid document item |
| `topic_coverage` | At least two distinct valid chunks |
| `bilateral_coverage` | Every comparison sub-query has matching Evidence |

## Retry Boundary

- A failed first retrieval may set `should_retry=true`.
- A failed second retrieval always sets `should_retry=false`.
- Runner must then return `no_relevant_context`; it must not keep looping.
