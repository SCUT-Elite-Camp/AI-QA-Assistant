# Phase 8: Wiki retrieval and explicit Agent exploration

## Goal and acceptance contract

The Agent starts with Direct Evidence search. When coverage is insufficient and exploration is enabled, it may call `wiki_search`, `wiki_read_page`, `wiki_read_sources`, then `wiki_search_evidence`. Wiki pages guide retrieval; only original, authorized, active-version Evidence may reach the Evidence Gate and citation validation. Wiki page scores are not fused into Direct Evidence scores.

Wiki navigation search combines scoped SQLite FTS and BGE-M3 page vectors with RRF. Both sources must use the same authorized scope and revision. The production navigation, exploration, vector-search, and publication switches stay disabled until release gates pass.

Acceptance requires the complete automated regression, an isolated real index and Agent run with version and permission probes, and Gate D on a frozen, human-adjudicated query set. The 12-page weak-label component probe is diagnostic only.

## Current verification

| Item | Status | Evidence and limit |
| --- | --- | --- |
| Direct-first explicit exploration through all four Wiki tools | PASS | Fake-backend Agent integration test; verifies tool order and return to source-version Evidence. |
| Wiki source version binding | PASS | Unit tests reject unrelated documents, absent or stale source versions, and wrong personal versions. |
| Local BGE-M3 encoder | PASS | Cached local model encoded one query as a 1024-dimensional vector; no live index or serving test. |
| 12-page retrieval component probe | PARTIAL | 20 Wiki-derived weak-label queries; no Agent run, human labels, citation, faithfulness, or latency gate. See `runs/wiki-retrieval-component-probe-12-20260916/report.json`. |
| Full Python suite | PASS | Final post-integration run: 487 passed, 2 skipped. The test-only optional-`pymilvus` stub exposes the `connect` interface; real Milvus tests remain skipped because the service/dependency is unavailable. This is local Gate A evidence, not a live Milvus pass. |
| Web regression and type check | PASS | 17 Vitest files / 73 tests passed; `vue-tsc --noEmit` passed. |
| Isolated real index and Agent tool-chain integration | PASS | Frozen 12-page source snapshots produced 211 original Evidence chunks in a local BM25 index; the isolated Wiki DB copy had 94 BGE-M3 vectors. The scripted run completed Direct → all four Wiki tools with five Wiki-scoped Evidence items accepted by Agent. See `runs/wiki-phase8-isolated-integration-verified-20260917/report.json`. |
| Isolated live-model Agent integration | PASS | DeepSeek v4 flash made the Agent decisions. One out-of-order repeated `wiki_search` was rejected; the successful calls then completed all four Wiki steps and Agent accepted 15 source-version-matched Evidence items. Personal scope and wrong knowledge base returned no Wiki pages. The source DB stayed DRAFT; only the isolated copy was activated. See `runs/wiki-phase8-live-model-staged-20260917/report.json`. |
| Live Milvus, Confluence service, and serving latency | NOT_RUN | The isolated probe used local BM25 Direct retrieval and a stored Confluence snapshot. It did not exercise the live service stack or Gate D latency conditions. |
| Gate D | NOT_RUN | `gate-d-query-template.json` is not frozen and lacks human relevance/reference labels. |

## Remaining work

1. Exercise the serving stack with an authorized active-version Milvus Direct Evidence backend when available. Record permission probes and stage latency. The isolated local probe cannot establish these properties for production.
2. Have people adjudicate and freeze Gate D queries, relevance pairs, reference answers, and rubrics before paired P0/P1 execution. Follow `gate-d-design.md`; do not reuse weak labels as ground truth.
3. Keep Gate C human Claim audit separate. AI review cannot sign its 100-Claim requirement.
