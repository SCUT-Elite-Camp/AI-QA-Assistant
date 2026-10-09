# Attachment Service

The private ingestion service scans and parses uploads, stores encrypted originals/evidence, and maintains an independent vector index for chat/topic attachments and Personal Library versions. Entry point: `python -m attachment_service` from this directory.

Use `.env.example` for configuration. Web and this service must share `ATTACHMENT_INTERNAL_SECRET` and `ATTACHMENT_ENCRYPTION_KEY`; secrets remain server-side. `ALLOW_FAKE_ATTACHMENT_SCANNER=false` in real acceptance. `ATTACHMENT_DATA_DIR` may point to a dedicated runtime directory.

Personal Library requires `PERSONAL_LIBRARY_ENABLED=true` and `ATTACHMENT_VECTOR_INDEX_ENABLED=true`. `ATTACHMENT_MILVUS_COLLECTION` must differ from enterprise `MILVUS_COLLECTION`. Search/outline/scoped request dimensions follow `LOCAL_EMBEDDING_MODEL_DIM` (bounded 1–65536), not a hardcoded 1024; the actual model and collection schema must match. The 2026-10-09 acceptance runtime uses 384.

Attachment metadata binds `chat_id`/`topic_id` and evidence version. Upload, chat attachment binding and Topic promotion synchronize both Web SQLite and this store; ownership alone does not permit use from an unrelated conversation. Personal scope requires matching owner/KB/Document/active Version. Web/Agent check the remote binding, current status and hashes before use and on citation reads. Expiry is epoch seconds.

API usage and failure semantics: [cross-layer contract](../docs/access-evidence-integration.md). Safe isolated startup and real probes: [runbook](../docs/access-evidence-runbook.md). Personal Library version/cleanup operations: [operations guide](../docs/personal-library-operations.md). Results and untested format/role/UI coverage: [acceptance/handoff](../docs/pr63-integration-acceptance.md).

From the repository root, run `python -m pytest attachment-service/tests`; these isolated tests may use fake scanners/transports, whereas real acceptance must exercise the actual configured scanner/parser/index/model.
