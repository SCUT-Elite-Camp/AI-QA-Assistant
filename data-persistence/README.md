# Data persistence

`data_persistence/` stores document/Topic/generated artifacts; `storage/` contains the enterprise vector/document and Wiki storage implementations. These are not anonymous source-serving APIs.

`AI_QA_DATA_DIR` can override the data root for an isolated runtime. Keep original data and collections intact when testing; the PR63 acceptance environment uses a dedicated documents projection, BM25 file, Research databases and Docker project outside the checkout. See the [runbook](../docs/access-evidence-runbook.md) for the exact environment contract.

The Web SQLite database is the identity/role/local ACL and durable conversation authority. Agent `WEB_SQLITE_PATH` must resolve the same database as Web `TURSO_DATABASE_URL`. Apply the full Drizzle journal through `0015_evidence_lineage.sql`; chats, topics, snapshots and facts carry evidence dependencies, and messages store proof in `parts`.

Stored content is not permanently authorized just because it exists on disk. The BFF/Agent recheck current local/native access, active source versions and hashes before model use or historical/Reader release. Unknown legacy derived data is quarantined. Wiki storage/build code is retained, but online navigation remains blocked until its metadata also proves full access lineage. Architecture: [access and evidence](../docs/access-evidence-architecture.md).

Run isolated checks from the repository root with `python -m pytest data-persistence/tests`. Those tests do not replace real source/permission/index acceptance. Do not delete an old collection or overwrite the original BM25 to address a dimension/path error; build and validate a separate projection first.
