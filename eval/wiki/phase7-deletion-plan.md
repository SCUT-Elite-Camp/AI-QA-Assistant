# Phase 7: Wiki source deletion and retraction

Status: PARTIAL. The Wiki-only deletion path is implemented and locally tested. Live Confluence deletion, physical Evidence/index cleanup, and production publication remain NOT_RUN. This extends the Phase 7 lifecycle requirement in the frozen Wiki refactor plan; it does not change the release gates.

## Goal

When a Confluence page disappears from a successful full-space export, its old document version must stop contributing to new Wiki revisions. A failed or partial export must not be interpreted as a deletion. Existing published Wiki content changes only through a reviewed, atomic revision.

## Required path

1. Treat only a `status=ok`, `full_sync=true` Confluence manifest for the same `space_id` as evidence that a page was removed. A page-only or partial export cannot revoke a page.
2. Compare the manifest's page IDs with the versioned, active Confluence JSON projection. Persist a scoped DELETE intent and a tombstone independently of whether a Wiki page currently refers to that document.
3. Coalesce rapid changes in the durable queue. A new active version may supersede an old deletion; a stale queued build must never save or publish a revision containing a tombstoned source.
4. Build the replacement Wiki revision from the active source set. Claims with no active source, orphan pages, links, and search entries disappear from the newly published revision. A failed replacement leaves the last published revision intact; while retraction is pending, affected old pages must not be served.
5. Keep original Evidence and Wiki roles separate. Physical deletion of RAG JSON, Milvus vectors, and BM25 entries is a separate ingestion lifecycle obligation and must not be reported complete from a Wiki-only rebuild.

## Acceptance checks

- Full successful export omitting a previously indexed page queues a DELETE and excludes that document from the worker source set; an empty full export also works.
- Partial and page-only manifests do not queue deletions. Invalid or conflicting manifests fail closed.
- The DELETE intent survives scheduling, worker restart, and retry. A delete during EXTRACT or FINALIZE cannot save/publish the old source.
- A newly active version after deletion can be built; stale old jobs cannot resurrect the deleted version.
- With publication enabled in a test store, the rebuilt active revision contains no removed source, unsupported Claim, orphan page, FTS hit, or active vector hit. Failed builds preserve the previous revision for audit while revoked sources are hidden from online Wiki reads.
- Production, tests, and eval/support changes are reported separately. Gate B remains a probe; Gate C needs 100 human-reviewed Claims and Gate D needs frozen queries. All production flags remain off until every gate passes.

## Local verification (2026-09-16)

- PASS: successful full manifest omission excludes the page and queues a durable DELETE; a partial or page-only manifest does not.
- PASS: SQLite tombstone remains after pending operations are scheduled, hides the old active revision from Wiki reads and vector search, and blocks stale save/publish in the same write transaction.
- PASS: a partial export cannot revive a tombstoned source; an explicit successful full export containing the page can.
- PASS: Wiki and adjacent search test selection, 74 passed. Full Python test selection passed with 474 passed and 2 skipped after using a short Windows pytest temporary path. Empty-data import smoke passed.
- PARTIAL: JSON, Milvus, and BM25 cleanup belongs to the upstream RAG document lifecycle and is not performed by this Wiki worker. No live Confluence deletion was executed.
- PASS: local Gate A Python tests and empty-data import check. The two skipped tests remain skips; this is local automation evidence only.
- NOT_RUN: human Gate C, frozen-query Gate D, live Confluence deletion, and production enablement.

## WeKnora design reference

WeKnora records a deletion tombstone, scrubs pending ingest, and persists retraction work even when no pages are visible yet. Its startup recovery requeues durable work. This project uses its existing SQLite queue and source-scoped atomic revisions instead of copying Redis/asynq or page-level LLM retraction.

- https://github.com/Tencent/WeKnora/blob/main/internal/application/service/knowledge_delete.go
- https://github.com/Tencent/WeKnora/blob/main/internal/container/recover_pending_wiki_tasks.go
