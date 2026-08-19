# Personal Library failure semantics and operations

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

## SourceIntent rollout

`SOURCE_INTENT_ROUTING_MODE` accepts `heuristic`, `shadow`, `canary`, or
`default`. Shadow is the safe initial default and logs only query hashes,
heuristic/structured/effective source names, selected tools, and evidence source
types. `SOURCE_INTENT_CANARY_PERCENT` deterministically selects canary traffic.
The heuristic remains available for one release as fallback and can be removed
only after benchmark and production shadow comparisons are accepted.
