# AI-QA-Assistant

2026-10-20：Fact 实现已移除，包括提议、确认、撤销、固定命令召回、API、界面、配置开关和模型上下文。当前会话记忆只包含 Snapshot 与 Tail；Topic 摘要独立保留。历史 Fact 设计与迁移仅供追溯，现存 `memory_facts` 表不再由应用读写，本次不清空运行数据库。Web 与 Agent 必须同步更新；旧 `facts` / `fact_proposals` / `recall` 字段不再属于内部契约。

AI-QA-Assistant is a multi-service question-answering application. The web UI, Agent API, retrieval/tooling code, and data services run as separate components.

Browse the [documentation index](docs/README.md) for module guides, current contracts, test reports and archived Q1 specifications.

Current common-integration baseline (2026-10-09): PR #63 (`cdbe02b`) plus access/evidence hardening on `integration/agent-demo-access-evidence`. Start with the [acceptance and handoff](docs/testing/integration/pr63-integration-acceptance.md), [security architecture](docs/access-evidence/access-evidence-architecture.md), [API integration contract](docs/access-evidence/access-evidence-integration.md), and [isolated runtime runbook](docs/access-evidence/access-evidence-runbook.md). These distinguish inherited features, new changes and unresolved quality gates; this is not a production-readiness claim.

## Architecture

| Component | Location | Responsibility | Local address |
| --- | --- | --- | --- |
| Web application | `frontend/` | Vue/Vite UI and Nitro server routes, sessions, and persistence | `http://localhost:3000` |
| Agent API | `agent/` (loaded by root `app.py`) | FastAPI chat and retrieval orchestration | `http://localhost:8000` |
| Tools and retrieval | `toolset/`, `data-pipeline/` | Tool implementations, ingestion and retrieval | Called by Agent |
| Data persistence | `data-persistence/` | Topic and generated artifact storage | Used by Agent and tools |
| Uploaded files | `toolset/tool_layer/parse_attachment_tool.py`, `data-pipeline/`, `data-persistence/` | Shared parsing, durable parsed context and automatic Personal Library ingestion | Agent `/private-files` |
| Vector and cache services | `docker-compose.yml` | Milvus and its etcd/MinIO dependencies, plus Redis | `localhost:19530`, `localhost:6379` |

The root `app.py` is a local development entry point that loads `agent/app.py` and adds the sibling code directories to Python's import path. Run it from the repository root so environment loading and path resolution use the expected project root.

Deep Research uses a human-approved plan over the authorized enterprise file catalogue,
parallel explorers, coordinator synthesis, independent review and bounded repair.
Only an exact reviewed revision approved by the coordinator is released. See the
[Research team architecture](agent/docs/research_team_architecture.md) for roles,
budgets, recovery and validation limits.

Local Research development can grant the complete file catalogue with
`RESEARCH_DEVELOPMENT_MODE=true` and a loopback `HOST`; production leaves the
flag false. The sequential Research runtime and executable UI Mock have been
removed; saved historical outputs remain readable, while execution uses a new
approved harness plan.

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

Source access uses `SOURCE_ACCESS_MODE=native`, `CONFLUENCE_AUTH_ENV_FILE` and `CONFLUENCE_BASE/EMAIL/TOKEN/ACCOUNT_BINDINGS`. Web's `TURSO_DATABASE_URL` must point to the same database as Agent's `WEB_SQLITE_PATH`. Isolate acceptance with `RESEARCH_DOCUMENTS_DIR`, `AI_QA_DATA_DIR`, `BM25_INDEX_PATH`, `TOPICS_DATA_DIR`, `RESEARCH_DATABASE_PATH`, `RESEARCH_CHECKPOINT_PATH` and `ATTACHMENT_DATA_DIR`. Private file APIs share the Agent process at `AGENT_BASE_URL/private-files`, using `ATTACHMENT_INTERNAL_SECRET`; only the Agent needs `ATTACHMENT_ENCRYPTION_KEY`. Actual embedding dimensions and separate enterprise/private collections use `LOCAL_EMBEDDING_MODEL_DIM`, `MILVUS_COLLECTION`, `ATTACHMENT_MILVUS_COLLECTION`. `AI_QA_BUILD_DIR` and `AI_QA_ACCEPTANCE_VOLUME_ROOT` can move build/Compose output to a disk with space. See the runbook for values and safe startup.

Apply the full Web migration journal through `0015_evidence_lineage.sql` (chat/topic/Memory provenance). Per the user's 2026-10-15 policy, ordinary chat/topic browsing reads saved snapshots after local identity/ownership/membership checks and does not revalidate their sources. Generation, Memory reuse and message-bound citation Reader retain current source checks. Ordinary Chat supports enterprise, personal and attachment sources; Research remains enterprise-only. Wiki navigation is quarantined until its own derived metadata has verifiable source lineage.

Pipeline modules are organized into `entrypoints/`, `documents/`, `files/`, `confluence/`, `ingestion/` and `indexing/`. The three file-selection entrypoints share `pipeline.ingestion.batch.run_batch`; document preparation, upload job state and the vector worker have separate modules. Use `python -m pipeline.entrypoints.process`, `pipeline.entrypoints.auto_process` or `pipeline.entrypoints.process_specific_files` from `data-pipeline/`.

Structured PDF/DOCX/XLSX table parsing, optional region OCR, semantic/display text views and chunk geometry are documented in the [current pipeline contract](docs/data-pipeline/DATA_PIPELINE.md). Existing Milvus reads remain compatible; structured ingestion requires the provenance schema before replacing vectors. Use separate collections for migration and follow the [table integration record](docs/data-pipeline/table-processing-integration-20261012.md) for validation limits.

2026-10-16: retrieval now supports a shared local English cross-encoder with a 20-candidate pool
and TopK output (default five). New ingestion uses token-bounded prose and table row groups,
preserves XLSX formulas/cached values and supplies separately identified neighboring context.
Install the pinned reranker weights before startup; see [Toolset configuration](toolset/README.md).
Existing data needs a separate index rebuild before switching; a code update alone does not
change old chunks. Source permission, version/hash and Reader checks remain required.

Latest desktop refinements and verification limits are recorded in the [2026-10-13 desktop retest](docs/testing/ui/desktop-ui-retest-20261013.md).

## CI and dependency compatibility

The Personal Library pull request workflow uses Python 3.11, Node.js 22, and pnpm 10. Its canonical install commands are:

```bash
python -m pip install -r requirements.txt
cd frontend && pnpm install --frozen-lockfile
```

Root `requirements.txt` also includes PDF table extraction and CPU OCR dependencies; no separate table requirements files are needed. Tesseract and its language data remain system dependencies.

The frontend lockfile is committed at `frontend/pnpm-lock.yaml`. Root Python requirements use conservative major-version bounds for direct dependencies; exact transitive versions are not locked, so this is a compatibility policy rather than a fully locked Python environment.
