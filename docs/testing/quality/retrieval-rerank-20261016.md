# English reranking and semantic chunk regression — 2026-10-16

Implementation is complete and an isolated candidate index is staged. The original
documents, BM25, vector collection and application configuration remain unchanged.
This is a local retrieval-component diagnostic, not production acceptance.

## Protocol

The run uses the actual configured BGE-small-en 384-dimensional embedding model,
Milvus and BM25, plus local `cross-encoder/ms-marco-MiniLM-L6-v2` at pinned revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. Each active channel retrieves 20 candidates;
Hybrid fuses a bounded pool and the cross-encoder returns TopK, default five.
Original neighboring chunks retain their own identities and hashes.

Twenty seen regression questions (70 required facts) and eight repair-informed
extensions/paraphrases (28 facts) were frozen before the four-way comparison.
Neither cohort is an unseen holdout. Early development probes informed the repairs
and are retained separately; final scores are post-repair regression results.
Codex reviewed source files, exact returned passages and row/column roles per fact.
Scripts aggregate those assignments, rather than grading by keywords. No answer
model or external judge API was called. `[Eval KB]` entries remain distractors in
the corpus but are not selected gold sources.

## Main regression results

Complete means every required fact from the designated source is supported.
Top5 counts primary hits; adjacent original context is separately identified.
The actual Fast context selector was replayed at 12,000 characters.

| Variant | Primary Top5 complete | Complete after context and Fast budget | Fact coverage after budget |
| --- | ---: | ---: | ---: |
| A: original chunks | 15/20 | 14/20 | 50/70 — 71.4% |
| B: original chunks + reranker | 17/20 | 16/20 | 61/70 — 87.1% |
| C: new chunks | 17/20 | 17/20 | 63/70 — 90.0% |
| D: new chunks + reranker | 17/20 | 18/20 | 66/70 — 94.3% |

D's actual pre-model candidate pool contains complete evidence for 18/20 questions;
the two PNGs are unindexed. All 560 D query/passage pairs fit the model input limit:
maximum 376 tokens, zero over 512. Primary Top5 alone is **17/20**, not 18/20.
The added original context recovers the missing AR-006 row for X01.

The eight repair-informed extension results after context/budget are A 4/8,
B 5/8, C 6/8 and D 7/8. Combined D is 25/28 questions and 93/98 facts (94.9%);
the cohorts must remain separately reported. E02 loses a requested Local Setup
excerpt despite finding compatible endpoint guidance in another document.

## Findings

- The plan's eight stop conditions were present in the original corpus but could
  be crowded out by repeated table views. Semantic reranking promotes the list.
- New prose keeps both halves of the SSE adapter/BFF release explanation together.
- The old XLSX row hits repeated a 14,950-character table that Fast excluded.
  New bounded row/field groups preserve AR-005/AR-006 identity, duration and stop
  reason. Reranking can still miss one requested row in primary Top5, so the
  separately bound neighboring context matters. Distant-row comparisons remain
  unverified; these results are not a universal cross-row guarantee.
- Cached XLSX results 5/2/4/6/3 are directly preserved with their formulas. Baseline
  counts were only derivable from explicit test-ID ranges. No recalculation ran.
- PDF naming underscores are preserved in their correct position; ordinary
  multiline numeric cells keep geometry order.
- Units/notes, context provenance, current-chunk Reader handling, owner/version
  filtering and guard propagation have focused regression coverage.
- Image OCR/diagram relationships remain outside this change. Two PNGs still have
  no indexed chunks. Alternate parent text is not counted as image extraction.

## Verification and limits

- Pipeline/Toolset/Persistence final full run: 631 passed, 2 opt-in Milvus tests skipped,
  17 subtests passed, including active-owner/version-before-inference coverage.
- Agent final full run: 1013 passed, including three new tests proving source denial
  escapes both enterprise search entry points and the personal tool wrapper.
  An earlier run hit the known Research demo instability;
  its isolated rerun and the later full run passed. Repeat stability is not claimed.
- Frontend: 316 tests/60 files passed; vue-tsc and production build passed. Build
  migration/output used a disposable SQLite database and output directory.
- All 112 final retrieval calls completed; B/D used actual cross-encoder weights
  with no ranking fallback. D median full local retrieval time was 1.46 seconds,
  P95 2.07 seconds, on four Torch CPU threads. This excludes live native-access/BFF
  checks and is not a load-test SLA. The first baseline query included an 11.40s
  cold embedding/collection initialization.
- The original vector collection remains at 1,167 entities. The isolated candidate
  has 782 chunks in 95 nonempty documents, maximum 3,296 characters/320 embedding
  tokens per chunk. All original source/projection/BM25 hashes remain unchanged.
- Current PDF/XLSX parser output reproduces the staged content and chunk text.
  Live BFF sessions/CSRF/native Confluence checks, browser UI, image understanding,
  and complete offline Wiki coverage were not accepted by this component run.
  Wiki navigation remains quarantined.

## Local evidence and activation

The local evidence bundle is `.local-backups/retrieval-rerank-20261016-01a13e93/`: full report,
frozen English questions, 112 raw results including actual candidate text,
per-fact reviewed support hashes, summary, source fingerprints, parser checks,
and local activation records. Source exports and weights are not
committed. The reproducible runner is `eval/retrieval_rerank_probe.py`.

The user explicitly authorized activation on 2026-10-16. Root and Agent local
configuration now select the verified document projections, BM25 and Milvus
collection recorded in `activation.json`. Existing databases, `AI_QA_DATA_DIR`
and private collections stay in place. The user subsequently authorized deletion
of the retired indexes and relocation of the new ones to the normal system paths:
`data-persistence/data/documents` and `data-persistence/data/bm25_index.pkl`.
No application services were running at activation, so the next start uses the
new configuration. No merge has been performed.

Activation exposed and fixed a path mismatch: the shared persistence resolver
now honors `RESEARCH_DOCUMENTS_DIR`, matching Agent source validation while
leaving other data paths unchanged. The focused storage/batch/retrieval suite
passed 49 tests, with 2 opt-in tests skipped and 17 subtests passed. A fresh
default-config smoke returned five verified excerpts with completed local
reranking in each of BM25, vector and hybrid modes. The active collection has
782 entities. Original integrity checks were made before the user-authorized
cleanup; they describe that historical state. This smoke does not claim live
BFF/native-permission acceptance.

Three reparsed bodies differ: the CP2 Excel report, User Guide PDF and semantic
benchmark PDF. Historical Reader citations bound to their prior parsed hashes can
receive 409 after a switch. Current hash/version checks remain intact; saved
chat/topic snapshot browsing follows the existing policy.

After activation, the user explicitly requested removal of retired indexes.
The old `rag_current_20261014` vector collection was deleted; the active collection
remains at 782 entities. After automatic safety review blocked filesystem removal,
the human confirmed deleting the retired projections, BM25 and baseline copies.
Old-index rollback is unavailable. The normal document/BM25 paths now contain the
NEW indexes and must not be treated as retired cleanup targets.

All 98 new projection files and the BM25 file were moved back to the repository
persistence directory; the entire evidence bundle was moved into the ignored
local backup directory. The former D-drive bundle no longer exists. SHA-256
checks matched every relocated index file. A fresh default-config smoke after
relocation passed BM25, vector and hybrid retrieval with five verified excerpts
and completed reranking in each mode. See `system-relocation-smoke.json` and the
updated `activation.json` in the local evidence bundle.
