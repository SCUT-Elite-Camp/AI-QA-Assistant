# Corrective Retrieval

## Purpose

`CorrectiveRetrievalPlanner` creates a bounded second retrieval request after
Evidence Gate rejects the first attempt.

## Rules

- Corrective retrieval may follow attempt 1 only.
- Every corrective request has `retrieval_attempt=2`.
- QueryPlan filters are hard constraints and are copied without relaxation.
- `top_k` is doubled but never exceeds 20.
- Retrieval mode changes deterministically:
  - Hybrid → BM25
  - BM25 → Vector
  - Vector → BM25
- For a comparison, only targets listed in
  `EvidenceGateResult.missing_targets` are retrieved again.
- If `should_retry=false`, no requests are created.

After attempt 2, Evidence Gate cannot request another retry.
