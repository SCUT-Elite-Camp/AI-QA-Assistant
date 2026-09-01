# Evidence Gate

## Diagnostic result

Every decision now records enough information for Agent-side diagnosis:

- `reason`: deterministic acceptance or rejection reason.
- `candidate_evidence_count`: evidence received before threshold filtering.
- `eligible_evidence_count`: evidence retained after filtering/deduplication.
- `rejected_evidence_count`: evidence removed by the Agent threshold.
- `covered_targets`: retrieval queries represented by eligible evidence.
- `missing_targets`: QueryPlan sub-queries that corrective retrieval should target.

If the bounded corrective pass still produces no acceptable evidence, Runner
returns `no_relevant_context` with
`evidence_insufficient_after_correction`. It must not ask the LLM to call the
tool again and then misreport the outcome as `policy_limit`.

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

## Answer Completeness Boundary

Accepted evidence does not guarantee that the generated answer uses every
material fact. After answer generation, `AnswerCompletenessChecker` compares the
answer with the `QueryPlan` aspects and accepted Evidence. It pays particular
attention to percentages, monetary amounts, dates, named entities, and both
sides of comparisons.

If the answer is incomplete, the Agent performs at most one repair call using
the existing Evidence. This step does not run retrieval or call a tool. A checker
failure preserves the original answer so that the quality guard cannot break the
main response path. Citation Check remains the final validation step after the
repaired answer has been formatted.

To control latency, completeness checking is tiered:

- Single-target ordinary answers use a deterministic local gate that validates
  whether the answer cites an accepted evidence item. This path makes no LLM call.
- Comparison, summarization, and plans with at least two sub-queries retain the
  semantic completeness review.
- The semantic review can use a stage-specific model through
  `ANSWER_COMPLETENESS_MODEL`; an empty value preserves the main-model fallback.
- A failed local or semantic check can trigger at most one repair using the
  already accepted evidence. It never starts another retrieval loop.
