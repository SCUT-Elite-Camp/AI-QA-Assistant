# Repository handoff rules

## Integration baseline

- The common integration branch is `integration/agent-demo-access-evidence`, based on PR #63 at `cdbe02b39793d0041f824e5409e93934f1810214`. Preserve inherited report-quality, retrieval, UI, and Personal Library fixes. Do not reset the separate dirty PR58 checkout.
- Read [README.md](README.md) and the four current docs: [architecture](docs/access-evidence/access-evidence-architecture.md), [integration contract](docs/access-evidence/access-evidence-integration.md), [runbook](docs/access-evidence/access-evidence-runbook.md), [acceptance/handoff](docs/testing/integration/pr63-integration-acceptance.md). Component instructions still apply unless the human explicitly authorizes cross-layer integration.
- The July Q1 specifications and dated partner test reports are historical evidence, not current authentication/run configuration. Do not edit their historical scores to claim new acceptance.

## Security and evidence

- Browser identity is session-owned. Bearer/shared internal secrets remain server-side. No anonymous fallback, browser-provided authorization contexts, positive-grant caching, or admin bypass of source-native permissions.
- Confluence authority is local ACL intersected with native read permission and explicit account/site bindings. `SOURCE_ACCESS_MODE=native`; `CONFLUENCE_AUTH_ENV_FILE` points at ignored credentials. Never commit populated `.env` files, source exports, model weights or runtime databases.
- Per the user's explicit 2026-10-15 policy, ordinary saved chat/topic navigation (lists, transcripts, favorites, topic summaries/document snapshots/dialogues) reads persisted data after current local identity/ownership/membership checks, without source-native or version/hash revalidation. Saved content may remain visible after its source changes or is revoked. This is snapshot browsing, never a positive source grant. Model calls, newly generated answer release, Memory reuse and citation Reader still recheck current sources and version/hash. Unknown lineage must not be backfilled or reused as trusted model evidence.
- Preserve ContextVar guards across thread-pool boundaries; do not use shared mutable last-request state.
- Research currently accepts enterprise Confluence only. Wiki-derived navigation is quarantined until it proves its own full source lineage. Do not relax either boundary to make a demo pass.
- Tests may inject fake transports/models. Real acceptance must use the actual model, embedding/Milvus, parser, BFF session/CSRF and native permissions. Attachment malware scanning was removed at the user's explicit request on 2026-10-12.

## State and runtime

- Web migration `0015_evidence_lineage.sql` adds lineage to chats/topics/memory snapshots/facts; message lineage lives in `parts`. Attachment Store/Web bind `chat_id`/`topic_id`. Attachment expiry is epoch seconds, not milliseconds.
- Run acceptance outside the checkout, with one shared `WEB_SQLITE_PATH`/`TURSO_DATABASE_URL`, `RESEARCH_DOCUMENTS_DIR`, `AI_QA_DATA_DIR`, `BM25_INDEX_PATH`, `TOPICS_DATA_DIR`, Research DB/checkpoint and attachment data paths.
- Isolated Compose uses `AI_QA_ACCEPTANCE_VOLUME_ROOT`, ports 19539/9099 and distinct enterprise/private collections. Do not delete original volumes or swap original indexes. `LOCAL_EMBEDDING_MODEL_DIM` must match both actual embedding and collection schema.
- Agent/Web share `AGENT_API_KEY` and `AGENT_INTERNAL_TOKEN`; private services share `ATTACHMENT_INTERNAL_SECRET`. `AI_QA_BUILD_DIR` can move build output off a full disk. Dev login/insecure cookies are loopback-only test settings, not production defaults.

## Verification and delivery

- All default tests and acceptance runs use English questions, assertions, fixtures, expected facts and generated answers (`en-US`). Use another language only for an explicitly identified language/Unicode capability test or when the user requests it. Translate into a new dataset/result version; retain historical evidence and never relabel seen translated cases as unseen holdouts. See the evaluation policy for the current default.

- Question design, source review, and answer grading default to Codex's per-case review. Do not call Groq or another external judge API for grading unless the user explicitly changes this policy. Groq may remain the actual answer model under test. Separate project documents from `[Eval KB]` fixtures; see [evaluation policy](docs/testing/quality/evaluation-policy.md).

- Agent: run `python -m pytest` from `agent/`. Frontend: `pnpm test`, `pnpm exec vue-tsc -p tsconfig.app.json --noEmit`, `pnpm build` from `frontend/`. Real runners use `python -m eval.integration_boundary_acceptance` / `eval.research_product_acceptance` from `agent/` (see runbook for prerequisites).
- The quality runner requires an explicit ACL-denied `--forbidden-doc-id`; question out-of-scope is not equivalent to unauthorized. Mutating negative probes are only allowed on a marked disposable fixture, restored in finally.
- Separate runtime pass, machine quality, human review and repeat stability. Keep repair-informed cases distinct from prefrozen holdouts; do not tune holdout answers and continue calling them unseen.
- Sync consumer-facing docs when changing interfaces, environment variables or schema. Include unresolved quality/UI coverage honestly in the final PR; do not merge `dev` without explicit authorization.
