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
material fact. After answer generation, `AnswerCompletenessChecker` derives a
short atomic target list and scores the answer with deterministic coverage.
LLM calls are reserved for target extraction (optional) and a single append-only
repair. The completeness *judge* path is no longer used.

If coverage finds a gap, the Agent performs at most one repair using the
existing Evidence. A coverage guard then compares the answer before and after
repair and rolls back if the rewrite is worse. Checker failures preserve the
original answer. Citation Check remains the final validation step after the
repaired answer has been formatted.

To control latency, completeness checking is tiered:

- Zero accepted evidence skips completeness entirely. That path is a retrieval
  problem, not an answer-repair problem.
- After an answer is generated, a deterministic coverage check compares the
  answer with atomic targets derived from the QueryPlan and accepted evidence
  (identifiers, numbers, dates). This path makes no LLM *judgment* call.
- Optional LLM target extraction (`ANSWER_TARGET_EXTRACT_LLM`) may run for
  complex queries to turn evidence into a short required-fact list. Extraction
  is an LLM strength; completeness judging is not.
- Gaps trigger at most one append-only repair that receives the missing list
  and only the evidence snippets that contain those facts.
- A coverage guard compares the answer before and after repair. Coverage drops
  or lost numeric atoms roll the answer back. Empty repairs are also rejected.
- `ANSWER_COMPLETENESS_MODEL` still selects a stage-specific model for
  extraction/repair; an empty value preserves the main-model fallback.
