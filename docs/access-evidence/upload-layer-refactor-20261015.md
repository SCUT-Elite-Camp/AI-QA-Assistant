# Upload layer refactor — 2026-10-15

Conversation uploads now follow the same layer boundaries as other tools:

```text
Web session/CSRF -> Agent upload API -> Toolset parse_attachment_context
  -> Pipeline parse_context -> text context returned for the conversation
  -> Data Persistence parsed snapshot + durable ingestion job
  -> Pipeline shared structured chunking / embedding / private collection
  -> Web background status sync -> desired-to-active Personal Library CAS
```

`toolset/attachment_service/` and its standalone launcher are removed. Toolset's
upload adapter only calls the public Pipeline parser, saves its result, and
returns `context/items`. PDF/DOCX/PPTX/XLSX use the existing Pipeline parsers;
supplemental text, image and legacy formats also enter the common registry.
The separate attachment chunker and structure builder are removed. Private
versions use `prepare_ingestion_chunks` and the common Section builder.

Data Persistence owns original blobs, metadata, evidence, parsed snapshots and
jobs. Saving a parse and queuing ingestion is transactional. A conversation upload
also allocates an owner-private library version. It receives the same parse,
without another format-parsing pass. The personal version has no chat expiry;
deleting the temporary attachment does not delete the library copy. Temporary
attachments do not build a second vector index. Indexing failure does not erase
the existing active library projection.

Private HTTP APIs are hosted at `AGENT_BASE_URL/private-files`, with the existing
internal secret and `/v1/**` paths. Python tools and AccessGuard use local
Pipeline/storage calls, avoiding synchronous self-HTTP deadlocks. Request-local
allowlists, personal HMAC context, owner/KB/active-version filtering, source hashes
and current permission checks remain in place. Shared handles do not cache grants.
Research remains restricted to enterprise Confluence.

Preserve the same `ATTACHMENT_DATA_DIR`, encryption key and private collections.
The SQLite schema adds `parsed_documents` without resetting existing data.
Stop the old attachment process before the Agent opens the same queue. Retire
`ATTACHMENT_SERVICE_URL`; configure Web's `AGENT_BASE_URL` and the matching secret.
Enable the library and private-vector flags for automatic indexed library use.

Verification runs are separate and are not combined into a real-acceptance score:

| Check | Result |
| --- | --- |
| Agent full suite | 966 passed |
| Toolset + Pipeline, excluding the missing PDF evaluation script test | 592 passed; 22 subtests passed |
| Final local-call / navigation / upload regression after retrieval cleanup | 18 passed |
| Frontend full suite | 299 passed, 58 files |
| Vue typecheck | Passed |
| Production build | Passed; migration database and build output outside checkout |

The Agent run included updating a stale streaming test double to accept the
existing `max_tokens` argument; production answer behavior was not changed.
New tests cover a single parse for conversation/library, independent deletion,
restart from the persisted parse without a raw file, transactional rollback,
hash drift, deletion during embedding, current-access rechecks without HTTP,
session-owned allocation, compensation and background activation.

The broader persistence check is not green: the checkout already lacks
`scripts/evaluate_pdf_parsing.py`, `scripts/check_milvus_provenance.py` and
`scripts/safe_reindex.py`; there are also Compose-image expectations and
host/collection-dependent storage test failures. Those scripts, original
indexes, volumes and source data were not restored or replaced by this change.
No real model/embedding/Milvus/native-permission or browser acceptance is claimed.
Historical acceptance scores are unchanged.
