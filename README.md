# AI-QA-Assistant

AI-QA-Assistant is a multi-service question-answering application. The web UI, Agent API, retrieval/tooling code, and data services run as separate components.

Current common-integration baseline (2026-10-09): PR #63 (`cdbe02b`) plus access/evidence hardening on `integration/agent-demo-access-evidence`. Start with the [acceptance and handoff](docs/pr63-integration-acceptance.md), [security architecture](docs/access-evidence-architecture.md), [API integration contract](docs/access-evidence-integration.md), and [isolated runtime runbook](docs/access-evidence-runbook.md). These distinguish inherited features, new changes and unresolved quality gates; this is not a production-readiness claim.

## Architecture

| Component | Location | Responsibility | Local address |
| --- | --- | --- | --- |
| Web application | `frontend/` | Vue/Vite UI and Nitro server routes, sessions, and persistence | `http://localhost:3000` |
| Agent API | `agent/` (loaded by root `app.py`) | FastAPI chat and retrieval orchestration | `http://localhost:8000` |
| Tools and retrieval | `toolset/`, `data-pipeline/`, `shared_runtime/` | Tool implementations, ingestion, retrieval, and shared runtime code | Called by Agent |
| Data persistence | `data-persistence/` | Topic and generated artifact storage | Used by Agent and tools |
| Private ingestion | `attachment-service/` | Scanning, parsing, encrypted attachments, Personal Library versions and separate private vectors | `http://localhost:8200` |
| Vector and cache services | `docker-compose.yml` | Milvus and its etcd/MinIO dependencies, plus Redis | `localhost:19530`, `localhost:6379` |

The root `app.py` is a local development entry point that loads `agent/app.py` and adds the sibling code directories to Python's import path. Run it from the repository root so environment loading and path resolution use the expected project root.

## Local development

On macOS/Linux, run the combined launcher from the repository root:

```bash
./start.sh
```

It prepares the Python virtual environment and frontend dependencies when missing, starts the Agent and Web processes, waits up to 60 seconds for the frontend and Agent readiness endpoint, and opens the UI when the frontend responds. It reports a degraded Agent separately so the UI can still be opened while retrieval startup is investigated. Press `Ctrl+C` to stop the launched services.

On Windows, use `start.ps1` or `start.bat`; they start the two services in separate terminal windows. For direct development, start the Agent from the repository root with `python -m app`, then start the web app from `frontend/` with `pnpm run dev` (or `npm run dev`).

The launcher does not start the vector/cache infrastructure. When a local task needs those services, start their Compose dependencies first:

```bash
docker compose up -d etcd minio milvus-standalone redis
```

## Readiness and troubleshooting

- `GET http://localhost:8000/health` is a liveness check: it confirms the Agent process responds.
- `GET http://localhost:8000/ready` reports whether retrieval and intent resources finished loading. A `degraded` response includes startup details; check the Agent terminal and required infrastructure/model configuration.
- The launcher probes `http://localhost:3000/` and the Agent `/ready` endpoint. A timeout or an exited child process is reported instead of being presented as a successful startup.
- If the web app cannot reach the Agent, check `AGENT_BASE_URL` and confirm it points to the same Agent instance used by the internal API client.
- If document retrieval returns no accessible results, check `WEB_SQLITE_PATH`, file ACLs, enabled user state, explicit native account/site binding, and Confluence read permissions. Local ACL or application admin status alone is insufficient. The local database default is `frontend/.data/sqlite.db`.

## Environment contract

Keep secrets in local, untracked environment files. Use `agent/.env.example` and `frontend/.env.example` as the templates for their respective services.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `AGENT_BASE_URL` | `frontend/.env` | Agent URL used by all Web-to-Agent clients. Development may omit it and use `http://127.0.0.1:8000`; deployed environments must set it. |
| `AGENT_API_KEY` | Agent and `frontend/.env` | Shared bearer key for public Agent business APIs. The values must match. |
| `AGENT_INTERNAL_TOKEN` | Agent and `frontend/.env` | Shared secret for internal Agent endpoints that require it. Keep it out of source control. |
| `WEB_SQLITE_PATH` | Agent environment | SQLite path used by Agent permission lookups. Defaults to `<repository>/frontend/.data/sqlite.db`. |

Other settings, including model credentials and database/session configuration, are documented in the component-level READMEs and environment examples. Never commit populated `.env` files.

Source access uses `SOURCE_ACCESS_MODE=native`, `CONFLUENCE_AUTH_ENV_FILE` and `CONFLUENCE_BASE/EMAIL/TOKEN/ACCOUNT_BINDINGS`. Web's `TURSO_DATABASE_URL` must point to the same database as Agent's `WEB_SQLITE_PATH`. Isolate acceptance with `RESEARCH_DOCUMENTS_DIR`, `AI_QA_DATA_DIR`, `BM25_INDEX_PATH`, `TOPICS_DATA_DIR`, `RESEARCH_DATABASE_PATH`, `RESEARCH_CHECKPOINT_PATH` and `ATTACHMENT_DATA_DIR`. Private transports require `ATTACHMENT_SERVICE_URL`, `ATTACHMENT_INTERNAL_SECRET`, `ATTACHMENT_ENCRYPTION_KEY`; actual embedding dimensions and separate enterprise/private collections use `LOCAL_EMBEDDING_MODEL_DIM`, `MILVUS_COLLECTION`, `ATTACHMENT_MILVUS_COLLECTION`. `AI_QA_BUILD_DIR` and `AI_QA_ACCEPTANCE_VOLUME_ROOT` can move build/Compose output to a disk with space. See the runbook for values and safe startup.

Apply the full Web migration journal through `0015_evidence_lineage.sql` (chat/topic/Memory provenance). Evidence reads are message-bound; stored answers/Memory are rechecked after revocation or version drift. Ordinary Chat supports enterprise, personal and attachment sources; Research remains enterprise-only. Wiki navigation is quarantined until its own derived metadata has verifiable source lineage.

## CI and dependency compatibility

The Personal Library pull request workflow uses Python 3.11, Node.js 22, and pnpm 10. Its canonical install commands are:

```bash
python -m pip install -r requirements.txt
cd frontend && pnpm install --frozen-lockfile
```

The frontend lockfile is committed at `frontend/pnpm-lock.yaml`. Root Python requirements use conservative major-version bounds for direct dependencies; exact transitive versions are not locked, so this is a compatibility policy rather than a fully locked Python environment.
