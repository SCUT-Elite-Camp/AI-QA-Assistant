# Gate D: frozen-query retrieval evaluation design

Status: **NOT_RUN**. The query set in `gate-d-query-template.json` has `frozen=false` and no queries. The 12-page Wiki revision is DRAFT. This document defines the evaluation contract; it supplies no relevance labels or measured results.

Gate C 的当前口径见 `gate-c-ai-plan-v2.md`；此处的 Gate D 冻结查询和标注要求未随之修改。

## Scope and comparison

Compare the same frozen queries, authorized corpus snapshot, active document versions, Direct Evidence index, model configuration, and answer policy:

| Arm | Retrieval path |
| --- | --- |
| P0 | Direct Evidence only |
| P1 | The same Direct Evidence pass, then the Agent's coverage assessment; when it finds a gap, `wiki_search → wiki_read_page → wiki_read_sources → wiki_search_evidence → Evidence Gate → Citation Validation` |

The P1 Wiki backend uses scope-filtered SQLite FTS and BGE-M3 vectors with RRF. Wiki pages are navigation metadata. Only original Evidence may enter the answer and citations. Do not blend Direct and Wiki scores or force Wiki exploration on simple queries. Keep all production feature flags off; any evaluation enablement must be isolated from serving configuration.

An eligible Wiki revision must be available to the *isolated* evaluation reader before P1 runs. The current DRAFT cannot be treated as a published result. Do not change or publish the current production revision to make the evaluation run.

## Freeze inputs before either arm

Create one UTF-8 JSON query file and record its SHA-256. It must contain:

- `dataset_id`, `schema_version`, `frozen=true`, `frozen_at`, `annotator_ids`, `corpus_snapshot_sha256`, `active_version_snapshot_sha256`, `wiki_revision`, and the exact configuration/commit identifiers for both arms.
- A stable `query_id`, verbatim query, one prespecified type (`cross_page`, `concept`, `entity`, or `simple_direct`), authorized source scope, owner and knowledge base identifiers, and expected answer facets for every query.
- Human-adjudicated relevant `(document_version_id, evidence_id)` pairs. A relevant pair must be an active, authorized version in the frozen corpus. Record relevance rationale and the annotator/adjudicator; AI-proposed labels alone are insufficient.
- A human-adjudicated reference answer or atomic answer facts, plus the citation and faithfulness rubric. Negative authorization/old-version probes must identify the forbidden scopes or versions without exposing their content in the expected answer.

Use the following keys in each `queries[]` item: `query_id`, `query`, `query_type`, `source_scope`, `owner_id`, `knowledge_base_id`, `expected_facets`, `relevant_evidence[]` (each entry has `document_version_id`, `evidence_id`, and `rationale`), `reference_answer`, `forbidden_scope_ids[]`, `forbidden_document_version_ids[]`, `annotator_ids[]`, and `adjudication_status`. The freeze validator must reject an empty relevant set for a recall query, missing reference/rubric, duplicate IDs, and `adjudication_status` other than `approved`.

Freeze all query types, relevance labels, negative probes, reference answers, scoring rubric, retry policy, warm-up count, repetitions, and latency environment together. A content change creates a new dataset ID and SHA; never edit labels after looking at P0/P1 results. Retain every failed or timed-out query in the denominator and the raw trace.

The current template is intentionally unfrozen. Generating candidate queries from the 12 source pages is allowed for annotation preparation, but those candidates are not ground truth until independently adjudicated and frozen.

## Execution record

For every `(query_id, arm, repetition)` save one append-only record with query-set SHA, corpus/index/model identifiers, timestamp, total wall time, Direct time, Wiki time, coverage decision, ordered tool calls, errors/timeouts, ordered final top-20 original Evidence IDs with document versions, retrieved contexts, answer, atomic claims, and final citations. Save Wiki page IDs separately and never count them as Evidence hits.

Run paired P0/P1 queries in interleaved order after the frozen warm-up. Use the same concurrency, host, network path, model settings, and cache policy; record hardware and service versions. Do not drop timeouts or failed calls. The frozen retry policy determines whether an error is retried; an unsuccessful query contributes zero recall and remains in latency accounting as the timeout duration.

Before scoring, validate that both arms contain exactly the frozen query IDs and repetition counts, with no extra IDs, duplicate records, corpus drift, or configuration drift. A mismatch makes the run **PARTIAL** and prevents Gate D `PASS`.

## Scoring

- **Recall@20**: for each query, distinct relevant `(document_version_id, evidence_id)` pairs in the ordered final top 20 divided by all frozen relevant pairs. Compute macro means separately for `cross_page`, `concept`, and `entity`, and for their prespecified combined set. **Each of the three types** must achieve relative gain `(P1 − P0) / P0 >= 10%`; also report the combined gain. A zero P0 denominator is unscorable, not an automatic pass.
- **Citation Precision**: human-adjudicated supported final citations divided by all final citations, using the frozen rubric. Missing required citations count as failures; report query-level and aggregate values. P1 must not be lower than P0.
- **Faithfulness**: evaluate final atomic answer claims against the actual original Evidence returned to that arm, using the frozen rubric. P1 must not be lower than P0. Ragas may be reported as a secondary automated estimate with its model/version, not substituted for human adjudication.
- **Unsupported Claim Rate**: unsupported final atomic claims divided by all final atomic claims under the same frozen human rubric. P1 must not exceed P0; unanswered queries remain visible and are scored by the frozen missing-answer rule.
- **Leakage**: scan Wiki pages, source IDs, retrieved Evidence, answer text, and citations against the query's authorized scope and frozen active versions. Any unauthorized or stale-version exposure fails the zero-leakage condition, even if the answer is otherwise correct.
- **Latency**: compute nearest-rank P95 from all frozen repetitions. For `simple_direct`, require `P1_P95 / P0_P95 <= 1.05`; for the prespecified Wiki-eligible complex-query cohort, require `P1_P95 / P0_P95 <= 1.25`. Also calculate the ratio on the actually explored subset and require it to be at most 1.25. Report the observed Wiki exploration rate and Direct/Wiki stage times. Freeze the eligible cohort before either arm runs; never use the observed subset alone to pass the gate.

Report per-query paired deltas, per-type counts, raw numerators/denominators, P50/P95, timeout counts, and any negative probe failures. Report `PASS` only if every required gate passes on a complete frozen run. Use `PARTIAL` for a complete run that misses a threshold or an incomplete paired run, and `NOT_RUN` while the query set or eligible P1 reader is unavailable. A `PROBE` on the 12-page draft is not Gate D certification.

## Remaining prerequisites

1. Complete the real document lifecycle integration and verify an eligible revision in an isolated evaluation environment.
2. Have people independently annotate and freeze the queries, relevance, references, and safety probes. The existing AI Claim countersign does not fill this role.
3. Build the paired trace collector and scorer against this contract, then run Gate D without changing frozen labels or thresholds.

Production navigation and publication flags remain disabled until the full release gates, including Gate C-AI under `gate-c-ai-plan-v2.md` and this Gate D, pass.
