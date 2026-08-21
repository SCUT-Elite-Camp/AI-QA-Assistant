# Personal Library deployment checklist

## Before deployment

- [ ] Pin the reviewed `toolset` commit and confirm `Personal Library P0` is green.
- [ ] Repository admin has configured the required check, or the exception is documented.
- [ ] Back up Web SQLite and Attachment Service data/blob storage.
- [ ] Provide secrets through the deployment secret manager.
- [ ] Set both Personal Library and attachment vector flags consistently.
- [ ] Confirm Personal and Enterprise Milvus collection names are distinct.
- [ ] Confirm embedding model and collection dimension match.

## Deploy and migrate

- [ ] Stop or drain writes during migration.
- [ ] Run Web `pnpm run db:migrate` once and retain its output.
- [ ] Confirm migrations `0004`, `0005`, `0006`, and `0007` are applied.
- [ ] Start Attachment Service and confirm fail-fast validation passes.
- [ ] Start Web, Agent, and cleanup worker.
- [ ] Confirm health checks and `/api/metrics` are reachable through normal auth/network boundaries.

## Smoke and security

- [ ] Upload a fixture and observe upload -> parse -> chunk -> embed -> index -> READY.
- [ ] Verify desired-to-active switch and citation provenance.
- [ ] Verify implicit Personal, Enterprise, mixed, and conversation-attachment routing.
- [ ] Verify cross-user, cross-KB, deleted, and inactive-Version access returns no data.
- [ ] Verify delete hides the document before physical cleanup completes.
- [ ] Complete all cases in `docs/personal-library-manual-acceptance.md`.

## Observability

- [ ] Dashboard cleanup pending/retry/dead counts and oldest-pending age.
- [ ] Alert on sustained ingestion failures, cleanup backlog, and dead jobs.
- [ ] Confirm logs contain correlation IDs but no bodies, embeddings, tokens, or secrets.
- [ ] Record baseline upload latency, READY latency, search latency, and cleanup completion time.

## Rollback readiness

- [ ] Record application, schema, Web database, and Attachment data snapshot versions.
- [ ] Verify the rollback build understands the applied schema.
- [ ] Do not reverse migrations in place; restore matching backups if schema rollback is required.
- [ ] Preserve the old active Version during failed upload/reindex recovery.

## Release record

- [ ] Deployment commit:
- [ ] CI run:
- [ ] Manual acceptance result:
- [ ] Operator and approver:
- [ ] Open exceptions and expiry:
