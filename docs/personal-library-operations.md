# Personal Library failure semantics and operations

## Feature configuration

Personal Library is disabled by default. Enable it only when the independent
attachment vector index is also enabled:

```env
PERSONAL_LIBRARY_ENABLED=true
ATTACHMENT_VECTOR_INDEX_ENABLED=true
ATTACHMENT_MILVUS_COLLECTION=attachment_evidence_cp2
```

`ATTACHMENT_MILVUS_COLLECTION` must not equal the enterprise
`MILVUS_COLLECTION`. Attachment Service validates both conditions at startup
and fails fast. `ATTACHMENT_INTERNAL_SECRET` and the attachment encryption key
must be supplied through the deployment secret manager; never commit their
real values.

## Deployment and migration

1. Back up the Web SQLite database and Attachment Service data directory.
2. Deploy Web and run `pnpm run db:migrate` before accepting traffic.
3. Confirm migrations `0004` through `0007` are recorded in Drizzle's journal.
4. Start Attachment Service with the final environment and confirm its startup
   configuration validation succeeds.
5. Start Web, Agent, and the cleanup worker; then check `/api/metrics`.
6. Run the smoke and security cases in
   `docs/personal-library-manual-acceptance.md` before enabling users.

Migration `0006_library_orphan_repair.sql` soft-deletes historical visible
Personal Library documents that have no Version. It deliberately avoids hard
deletion. Migration `0007_library_cleanup_jobs.sql` adds the durable deletion
outbox and its claim/idempotency indexes.

## Upload and version activation

Web calls Attachment Service before opening a local transaction. A new logical
Document, its first Version, `latestVersionNumber`, and `desiredVersionId` are
then committed atomically. If the local transaction fails, Web rolls back every
local row and performs best-effort deletion of the remote version.

Subsequent version numbers are allocated under a per-Document process lock and
an SQLite `BEGIN IMMEDIATE` transaction. The database counter comparison and
unique indexes remain the cross-instance safety boundary. A READY version is
activated only while it is still desired; indexing failure leaves the previous
active version online.

## Authorization boundary

Every Personal Library Web route resolves the authenticated user's default
personal KnowledgeBase on the server and applies one shared predicate:

```text
ownerUserId = principal
AND knowledgeBaseId = resolved personal KB
AND sourceScope = personal
AND deletedAt IS NULL
```

Agent `SourceIntent` only selects candidate sources. The HMAC-signed
`personal_library_context`, Personal/Enterprise Milvus collection separation,
and server-side candidate filters remain the authorization boundary.

## Delete and cleanup outbox

Logical deletion, clearing active/desired pointers, and inserting one durable
`library_cleanup_jobs` row per remote Version happen in one Web database
transaction. The document becomes immediately invisible after commit.

The request then attempts a fast-path remote DELETE. A Nitro worker claims
pending/retry jobs atomically with a time-limited lease, so an expired
`processing` job is recoverable after restart. DELETE 2xx and 404 complete the
job; 429, 5xx, timeouts, and network errors retry with exponential backoff and
jitter; permanent 4xx or exhausted retries become `dead`.

Operators can inspect `/api/metrics` under `libraryCleanup` for pending, retry,
dead, oldest-pending age, attempt total, and success total. Structured events
are `LIBRARY_CLEANUP_COMPLETE`, `LIBRARY_CLEANUP_RETRY`,
`LIBRARY_CLEANUP_DEAD`, and `LIBRARY_CLEANUP_WORKER_ERROR`; logs include IDs and
error codes but never document bodies, embeddings, HMAC tokens, or secrets.

### Retry and dead-job operation

- A growing `pending` count or oldest-pending age indicates a stopped worker or
  unreachable Attachment Service.
- `retry` jobs are claimed automatically after `nextAttemptAt`; do not edit
  attempt counters by hand.
- A `dead` job requires an operator to verify the remote object identifier and
  the permanent error, restore the dependency or configuration, and then use a
  reviewed database operation to return that job to `pending`.
- Remote DELETE is idempotent: both 2xx and 404 complete a job. Duplicate jobs
  therefore do not restore visibility or produce an authorization gap.

There is currently no supported dead-job administration UI. Direct database
changes require a backup, peer review, and an audit record.

## Reindex and failure recovery

Reindex builds a new projection before switching it active. Do not delete or
disable the current active Version before the replacement reports READY.
Parser, embedding, vector insertion, or index failures leave the old active
Version searchable. Retry the failed Version only after the underlying
dependency is healthy; verify `desiredVersionId` still refers to it before
expecting automatic activation.

If Web cannot synchronize a READY status, leave the current active Version in
place and retry status synchronization. Do not repair active/desired pointers
by timestamp alone: `versionNumber` and the desired-version compare-and-switch
are the ordering contract.

## Observability and privacy

Monitor cleanup counts, oldest pending age, attempts and successes together
with Attachment Service ingestion state transitions. Correlate events using
document, version, job, and safe principal-hash identifiers. Logs must not
contain document bodies, snippets beyond approved citation output, embeddings,
access tokens, HMAC contexts, encryption keys, or internal secrets.

## Rollback

Application rollback is safe only when the target build understands the
already-applied schema. Do not reverse migrations `0004`-`0007` in place.
Instead, stop writes, restore the pre-deployment SQLite backup if a schema
rollback is truly required, and restore the matching Attachment Service data
snapshot. After an application-only rollback, keep the cleanup worker running
if the old build supports the outbox; otherwise pause deletion operations until
a compatible worker is restored.

## Troubleshooting

| Symptom | Check | Safe action |
| --- | --- | --- |
| Startup says Personal Library requires vector indexing | The two feature flags | Enable both, or disable Personal Library |
| Startup reports collection collision | Personal and enterprise collection names | Assign a distinct attachment collection |
| Upload remains processing | Attachment status, worker logs, parser/model health | Restore dependency and retry; keep old active Version |
| New Version is READY but not active | `desiredVersionId`, version number, status sync | Retry sync; do not force an older undesired Version active |
| Deleted file remains in storage | Cleanup job state and remote DELETE result | Restore worker/network; allow idempotent retry |
| Cleanup job is dead | Permanent 4xx, attempts, remote ID | Correct configuration/data, then reviewed requeue |
| Personal search returns no result | feature flags, trusted context, active Version, owner/KB scope | Fix configuration or ingestion; never weaken filters |

## SourceIntent rollout

`SOURCE_INTENT_ROUTING_MODE` accepts `heuristic`, `shadow`, `canary`, or
`default`. Shadow is the safe initial default and logs only query hashes,
heuristic/structured/effective source names, selected tools, and evidence source
types. `SOURCE_INTENT_CANARY_PERCENT` deterministically selects canary traffic.
The heuristic remains available for one release as fallback and can be removed
only after benchmark and production shadow comparisons are accepted.
