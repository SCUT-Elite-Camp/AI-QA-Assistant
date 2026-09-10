# [2026-W30] Web Module (UI & Full-stack Gateway) Weekly Deliverable Report

> **Sprint Period**: 2026-07-20 to 2026-07-26 | **Module**: `web`
> **Contributors**: YourGitHubUsername, cheng-sh | **Status**: 🟢 Completed

---

## 1. Executive Summary
This report details the work delivered for the **Web Module (UI & Full-stack Gateway)** during **2026-W30**.
**Module Scope**: Frontend UI components, chat view, document viewer, settings drawer, and server-side API proxy.

### Key Highlights & Deliverables
- **Total Commits**: 3
- **New Features Delivered**: 2
- **Bug Fixes Resolved**: 0
- **Other Improvements**: 1

## 2. Work Breakdown & Deliverables

### 🚀 New Features & Enhancements
- **`a9c20c7f9`** - feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring *(by @cheng-sh on 2026-07-26)*
- **`40637f220`** - feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring *(by @cheng-sh on 2026-07-26)*

### 🛠️ Refactoring & Engineering Tasks
- **`1e4d97ed3`** - system update *(by @YourGitHubUsername on 2026-07-20)*

## 3. Impacted Code Files
| Action | File Path |
| :--- | :--- |
| `MODIFIED` | `agent/.env.example` |
| `MODIFIED` | `agent/README.md` |
| `MODIFIED` | `agent/agent/agent.py` |
| `MODIFIED` | `agent/agent/api/chat_routes.py` |
| `MODIFIED` | `agent/agent/config/settings.py` |
| `MODIFIED` | `agent/tests/conftest.py` |
| `MODIFIED` | `agent/tests/unit/test_answer_formatter.py` |
| `MODIFIED` | `data-persistence/storage/milvus_store.py` |
| `MODIFIED` | `data-persistence/tests/test_storage.py` |
| `ADDED` | `data-pipeline/pipeline/auto_process.py` |
| `MODIFIED` | `data-pipeline/pipeline/embedder.py` |
| `ADDED` | `docs/api.md` |
| `ADDED` | `docs/requirements.md` |
| `ADDED` | `eval/README.md` |
| `ADDED` | `eval/eval_questions_msmarco.json` |
| `ADDED` | `eval/eval_results_msmarco_run.json` |
| `ADDED` | `eval/evaluator.py` |
| `ADDED` | `eval/import_local_msmarco.py` |
| `ADDED` | `eval/metrics.py` |
| `ADDED` | `eval/ms_marco_eval.py` |
| `ADDED` | `eval/msmarco_qa_pairs.json` |
| `ADDED` | `eval/msmarco_qa_pairs.jsonl` |
| `ADDED` | `eval/prepare_msmarco_eval.py` |
| `ADDED` | `eval/run_eval.py` |
| `ADDED` | `eval/test_eval.py` |
| `MODIFIED` | `start_project.py` |
| `ADDED` | `toolset/tests/test_registry.py` |
| `MODIFIED` | `toolset/tool_layer/__init__.py` |
| `ADDED` | `toolset/tool_layer/registry.py` |
| `MODIFIED` | `toolset/tool_layer/search_tool.py` |
| `MODIFIED` | `web/.env.example` |
| `MODIFIED` | `web/package.json` |
| `MODIFIED` | `web/pnpm-lock.yaml` |
| `ADDED` | `web/server/plugins/observability.ts` |
| `MODIFIED` | `web/server/routes/api/chats/[id].post.ts` |
| `ADDED` | `web/server/routes/api/metrics.get.ts` |
| `ADDED` | `web/server/routes/api/telemetry.post.ts` |
| `MODIFIED` | `web/server/utils/drizzle.ts` |
| `ADDED` | `web/server/utils/logger.ts` |
| `ADDED` | `web/server/utils/metrics.ts` |
| `ADDED` | `web/server/utils/trace.ts` |
| `ADDED` | `web/src/composables/useBffChat.ts` |
| `DELETED` | `web/src/composables/useMockChat.ts` |
| `ADDED` | `web/src/composables/usePerformanceObserver.ts` |
| `MODIFIED` | `web/src/layouts/default.vue` |
| `DELETED` | `web/src/mock/errorMap.ts` |
| `DELETED` | `web/src/mock/mockAgent.ts` |
| `DELETED` | `web/src/mock/types.ts` |
| `MODIFIED` | `web/src/pages/chat/[id].vue` |
| `MODIFIED` | `web/src/pages/index.vue` |
| `MODIFIED` | `web/src/route-map.d.ts` |

## 4. Git Commit Verification Log
| Short Hash | Author | Date | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `1e4d97ed3` | YourGitHubUsername | 2026-07-20 | `Maintenance / Chore` | system update |
| `a9c20c7f9` | cheng-sh | 2026-07-26 | `Feature` | feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring |
| `40637f220` | cheng-sh | 2026-07-26 | `Feature` | feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring |

---
## 5. Next Sprint Outlook
- Continue integration and refinement based on cross-module milestones.
- Address feedback and optimize test coverage for modified files.
