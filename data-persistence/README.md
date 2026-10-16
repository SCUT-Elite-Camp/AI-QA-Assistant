# Data persistence

`data_persistence/` stores document/Topic/generated artifacts; `storage/` contains the enterprise vector/document and Wiki storage implementations. These are not anonymous source-serving APIs.

Uploaded originals, evidence, versions, encrypted blobs and parsed snapshots now belong to
`data_persistence.private_files` and `file_crypto`. `save_parsed_document` commits the parsed
context plus a library ingestion job in one SQLite transaction. Pipeline consumes that
snapshot without parsing the original again. Conversation uploads have an independent
owner-private library version; chat expiry/deletion does not remove that version. Preserve
`ATTACHMENT_DATA_DIR`, the encryption key and existing private collections during migration.
The SQLite schema adds `parsed_documents` automatically; no data reset is required.

File configuration and request models belong to `data_persistence.file_settings`
and `data_persistence.file_contracts`. Wiki path resolution is exposed through
`data_persistence.wiki.resolve_wiki_db_path`; its implementation lives alongside
the other persistence path resolvers. Relocating these modules does not change
the default attachment directory or existing environment-variable meanings.

`AI_QA_DATA_DIR` can override the data root for an isolated runtime. Keep original data and collections intact when testing; the PR63 acceptance environment uses a dedicated documents projection, BM25 file, Research databases and Docker project outside the checkout. See the [runbook](../docs/access-evidence/access-evidence-runbook.md) for the exact environment contract.

The Web SQLite database is the identity/role/local ACL and durable conversation authority. Agent `WEB_SQLITE_PATH` must resolve the same database as Web `TURSO_DATABASE_URL`. Apply the full Drizzle journal through `0015_evidence_lineage.sql`; chats, topics, snapshots and facts carry evidence dependencies, and messages store proof in `parts`.

Stored content is not permanently authorized just because it exists on disk. The BFF/Agent recheck current local/native access, active source versions and hashes before model use or historical/Reader release. Unknown legacy derived data is quarantined. Wiki storage/build code is retained, but online navigation remains blocked until its metadata also proves full access lineage. Architecture: [access and evidence](../docs/access-evidence/access-evidence-architecture.md).

Run isolated checks from the repository root with `python -m pytest data-persistence/tests`. Those tests do not replace real source/permission/index acceptance. Do not delete an old collection or overwrite the original BM25 to address a dimension/path error; build and validate a separate projection first.


文件向量后端通过 `data_persistence.vector.get_file_vector_store()` 复用公共 `MilvusStore`；
仅连接目标和集合隔离，不提供另一套 embedding/向量写入实现。
`ATTACHMENT_MILVUS_COLLECTION` 不得与企业 Evidence 或 Section 集合重名。
公共连接失败退避由 `MILVUS_CONNECT_RETRY_SECONDS` 控制，默认 30 秒。


存储回归默认使用临时 JSON 目录及模拟向量后端，不在导入测试时探测本地 Milvus。
真实 Milvus 存储测试需显式设置 `RUN_MILVUS_INTEGRATION=1`，连接使用
`MILVUS_HOST`/`MILVUS_PORT`，每项测试创建唯一的 `test_disposable_*` 集合并在结束后清理。
未开启时两项真实存储测试显示为 skipped，不能据此宣称真实服务验收通过。
