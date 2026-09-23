# Personal Library follow-ups

These items do not block the frozen implementation but should remain visible.

## P1 - Operations

- Repository admin: require the `Personal Library P0` check on protected merge branches.
- Add an authenticated dead-job inspection/requeue UI with audit history.
- Publish cleanup and ingestion dashboards with environment-specific alert thresholds.
- Define retention and physical purge policy for inactive Versions, blobs, vectors, and completed jobs.
- Run and record the 12-case human acceptance in a production-like environment.

## P2 - Developer experience

- Reduce the current ESLint baseline of 389 warnings without weakening rules.
- Update GitHub Actions/runtime dependencies before the Node.js 20 action-runtime warning becomes an enforced failure.
- Remove the legacy SourceIntent heuristic fallback after one accepted shadow/canary release and benchmark review.
- Make local Windows Web build dependencies self-contained so validation does not depend on junction behavior.

## P3 - Product enhancement

- Add per-user storage/document quotas and operator-visible usage accounting.
- Add user-facing cleanup/retry status without exposing internal object identifiers.
- Add richer citation navigation for PDF pages, Markdown sections, and spreadsheet ranges.
- Calibrate cross-source retrieval scores using production relevance judgments.
