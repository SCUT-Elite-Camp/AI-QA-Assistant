# Personal Library implementation report

## Scope and frozen implementation

The production implementation was frozen at `792c3c19b31af190db5b9aee407f50cf8a925c62`
on branch `toolset`. It preserves the KnowledgeBase -> Document -> Version
model, trusted HMAC context, independent Personal Library vector collection,
active/desired version ordering, active-only retrieval, citation provenance,
and asynchronous durable cleanup.

The implementation series started from `d4d5456` and contains 22 focused
commits across configuration, transaction/version safety, authorization,
cleanup durability, SourceIntent, tests, CI, and operations. Six pushes were
used during CI stabilization. The first three SQLite CI repair pushes were
incremental and did not fully address the test-database isolation root cause;
`07f549c` resolved it with a shared in-memory SQLite database, and `792c3c1`
completed clean-checkout Web typecheck compatibility.

## Implemented controls

- Startup rejects Personal Library enabled without attachment vector indexing.
- Document plus initial Version and pointers are committed atomically; remote
  cleanup is attempted if the local transaction rolls back.
- Version numbers are ordered and unique per Document; desired-version CAS
  prevents an older late-completing Version from replacing a newer one.
- All Personal Library Web access uses authenticated owner, server-resolved
  personal KnowledgeBase, personal scope, and non-deleted predicates.
- Logical delete and cleanup outbox insertion share one transaction. Retry,
  leases, dead state, idempotent 404 handling, metrics, and structured logs are
  implemented.
- SourceIntent supports personal, enterprise, conversation attachment, web,
  and mixed source selection without participating in authorization or adding
  a separate classifier round trip.
- Personal citations retain document/version/chunk/locator provenance and are
  excluded from the enterprise topic-document pool.

## Validation archive

The final implementation CI run is GitHub Actions workflow `Personal Library
P0`, run `32492222579`, job `96802302691`, status `success`, against
`792c3c19b31af190db5b9aee407f50cf8a925c62`.

Recorded final implementation results:

- Personal Library Python P0: 115 passed, 0 failed, 2 warnings.
- Agent full unit suite: 233 passed, 0 failed.
- Web Vitest: 60 passed, 0 failed.
- ESLint: 0 errors, 389 warnings.
- Web typecheck: passed.
- Web build: passed in GitHub Actions.

These automated results prove code-level contracts, not production
infrastructure, browser behavior, or human acceptance. Follow the manual
acceptance and deployment checklists before release.

Finalization was also validated locally after adding documentation and manual
fixtures:

- Personal Library Python P0: 115 passed, 0 failed, 3 dependency warnings.
- Agent full suite: 233 passed, 0 failed, 3 dependency warnings.
- Web Vitest: 60 passed, 0 failed.
- ESLint: 0 errors, 389 warnings.
- Web typecheck: passed.
- Web production build and SQLite migration: passed.

No production source file was changed during finalization. Human acceptance
remains pending, so the Personal Library must not yet be described as fully
accepted in a live environment.

## Repository governance

The current account can push but does not have admin or maintain permission.
No branch ruleset requiring `Personal Library P0` could be configured. A
repository administrator must add that required check for `toolset` (and any
merge target) before treating the branch as protected.
