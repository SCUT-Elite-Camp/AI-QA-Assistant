# Wiki release gate adjustment (2026-09-17)

The project owner indicated that the current quality is sufficient to waive the remaining Gate C review work and the frozen-query requirement for Gate D. This changes the release decision policy; it does not change measured results or retroactively make either gate pass.

## Recorded status

- Gate A local automated suite: PASS on the current code snapshot.
- Gate B frozen 12-page comparison: PROBE PASS on revision `wr_95886d6fc38a1ded1dd8128d`.
- Gate C: PARTIAL. Human review covered 230 Candidates, 62 Identities, 75 pages, 598 final Claims, 722 audit events and 8 repair events. Candidate precision, Claim precision and erroneous-merge thresholds pass. Semantic duplicate rate and human Evidence-location precision remain NOT_RUN.
- Gate D frozen-query evaluation: NOT_RUN. Isolated Milvus/BGE-M3 and Agent exploration integration passed, but it does not measure relative retrieval value or production latency.

## Preconditions before any Wiki content is made visible

1. Remove or correct the 10 human-rejected final Claims and their invalid audit events using a general modality/status-preservation rule. Do not add person-, page- or failure-specific production exceptions.
2. Reassess the 9 invalid PROMOTED Candidates, 5 unworthy REVIEWING pages and 8 unsupported summaries on REVIEWING pages. Keep rejected content out of the visible revision.
3. Rebuild the same frozen source cohort, rerun Gate A and Gate B, and verify exact Claim text/source sets, scope, active-version isolation, and original Evidence citation behavior on the resulting revision.
4. Record which human decisions remain applicable by exact identity plus unchanged source/Claim content. Changed or newly generated content requires fresh review or exclusion.
5. Keep release visibility limited to content that passes the above checks. Preserve a rollback path and observe errors and unsupported answers after activation.

The waiver does not authorize a false PASS label, mutation of the original human review, or deployment of the current DRAFT revision. The current revision contains known unsupported Claims on REVIEWING pages. Wiki ingest, publish and navigation flags stay disabled until a corrected, reviewable release candidate is ready.
