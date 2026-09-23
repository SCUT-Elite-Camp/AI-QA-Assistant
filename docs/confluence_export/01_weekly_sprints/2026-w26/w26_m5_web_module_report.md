# [2026-W26] Web Module (UI & Full-stack Gateway) Weekly Deliverable Report

> **Sprint Period**: 2026-06-22 to 2026-06-26 | **Module**: `web`
> **Contributors**: cheng-sh | **Status**: 🟢 Completed

---

## 1. Executive Summary
This report details the work delivered for the **Web Module (UI & Full-stack Gateway)** during **2026-W26**.
**Module Scope**: Frontend UI components, chat view, document viewer, settings drawer, and server-side API proxy.

### Key Highlights & Deliverables
- **Total Commits**: 1
- **New Features Delivered**: 1
- **Bug Fixes Resolved**: 0
- **Other Improvements**: 0

## 2. Work Breakdown & Deliverables

### 🚀 New Features & Enhancements
- **`66c976717`** - Add web files from HTC-web *(by @cheng-sh on 2026-06-26)*

## 3. Impacted Code Files
| Action | File Path |
| :--- | :--- |
| `ADDED` | `web/.gitignore` |
| `ADDED` | `web/.vscode/extensions.json` |
| `ADDED` | `web/README.md` |
| `ADDED` | `web/bff/README.md` |
| `ADDED` | `web/bff/pom.xml` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/BffApplication.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/config/CorsConfig.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/controller/ChatController.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/controller/HealthController.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/dto/ChatRequest.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/dto/ChatResponse.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/dto/Citation.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/dto/package-info.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/exception/package-info.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/service/ChatService.java` |
| `ADDED` | `web/bff/src/main/java/com/htc/bff/service/package-info.java` |
| `ADDED` | `web/bff/src/main/resources/application.properties` |
| `ADDED` | `web/bff/src/test/java/com/htc/bff/ChatControllerTest.java` |
| `ADDED` | `web/bff/src/test/java/com/htc/bff/HealthControllerTest.java` |
| `ADDED` | `web/docs/README.md` |
| `ADDED` | `web/docs/agent.md` |
| `ADDED` | `web/docs/api-contract.md` |
| `ADDED` | `web/docs/api.md` |
| `ADDED` | `web/docs/july-demo-delivery-scope.md` |
| `ADDED` | `web/docs/q1-three-phase-plan.md` |
| `ADDED` | `web/docs/q1-web-architecture-refinement.md` |
| `ADDED` | `web/docs/vibe-guide.md` |
| `ADDED` | `web/docs/vibe-log.md` |
| `ADDED` | `web/drizzle.config.ts` |
| `ADDED` | `web/eslint.config.ts` |
| `ADDED` | `web/index.html` |
| `ADDED` | `web/package.json` |
| `ADDED` | `web/pnpm-lock.yaml` |
| `ADDED` | `web/pnpm-workspace.yaml` |
| `ADDED` | `web/public/logo.svg` |
| `ADDED` | `web/server/database/migrations/0000_fuzzy_valeria_richards.sql` |
| `ADDED` | `web/server/database/migrations/0001_panoramic_giant_man.sql` |
| `ADDED` | `web/server/database/migrations/0002_clever_domino.sql` |
| `ADDED` | `web/server/database/migrations/meta/0000_snapshot.json` |
| `ADDED` | `web/server/database/migrations/meta/0001_snapshot.json` |
| `ADDED` | `web/server/database/migrations/meta/0002_snapshot.json` |
| `ADDED` | `web/server/database/migrations/meta/_journal.json` |
| `ADDED` | `web/server/database/schema.ts` |
| `ADDED` | `web/server/middleware/csrf.ts` |
| `ADDED` | `web/server/plugins/migrations.ts` |
| `ADDED` | `web/server/routes/api/chats.get.ts` |
| `ADDED` | `web/server/routes/api/chats.post.ts` |
| `ADDED` | `web/server/routes/api/chats/[id].delete.ts` |
| `ADDED` | `web/server/routes/api/chats/[id].get.ts` |
| `ADDED` | `web/server/routes/api/chats/[id].post.ts` |
| `ADDED` | `web/server/routes/api/chats/messages/[id].delete.ts` |
| `ADDED` | `web/server/routes/api/chats/title/[id].patch.ts` |
| `ADDED` | `web/server/routes/api/chats/visibility/[id].patch.ts` |
| `ADDED` | `web/server/routes/api/chats/votes/[id].get.ts` |
| `ADDED` | `web/server/routes/api/chats/votes/[id].post.ts` |
| `ADDED` | `web/server/routes/api/session.ts` |
| `ADDED` | `web/server/routes/auth/github.get.ts` |
| `ADDED` | `web/server/utils/drizzle.ts` |
| `ADDED` | `web/server/utils/session.ts` |
| `ADDED` | `web/server/utils/tools/chart.ts` |
| `ADDED` | `web/server/utils/tools/weather.ts` |
| `ADDED` | `web/shared/utils/models.ts` |
| `ADDED` | `web/src/App.vue` |
| `ADDED` | `web/src/api/agentApi.ts` |
| `ADDED` | `web/src/assets/css/main.css` |
| `ADDED` | `web/src/components/ModalConfirm.vue` |
| `ADDED` | `web/src/components/ModalRename.vue` |
| `ADDED` | `web/src/components/ModelSelect.vue` |
| `ADDED` | `web/src/components/Navbar.vue` |
| `ADDED` | `web/src/components/UserMenu.vue` |
| `ADDED` | `web/src/components/chat/ChatTitle.vue` |
| `ADDED` | `web/src/components/chat/ChatVisibility.vue` |
| `ADDED` | `web/src/components/chat/Comark.ts` |
| `ADDED` | `web/src/components/chat/Indicator.vue` |
| `ADDED` | `web/src/components/chat/SourceLink.vue` |
| `ADDED` | `web/src/components/chat/message/MessageActions.vue` |
| `ADDED` | `web/src/components/chat/message/MessageContent.vue` |
| `ADDED` | `web/src/components/chat/message/MessageEdit.vue` |
| `ADDED` | `web/src/components/chat/tool/Chart.vue` |
| `ADDED` | `web/src/components/chat/tool/Sources.vue` |
| `ADDED` | `web/src/components/chat/tool/Weather.vue` |
| `ADDED` | `web/src/composables/useBffChat.ts` |
| `ADDED` | `web/src/composables/useChatActions.ts` |
| `ADDED` | `web/src/composables/useChats.ts` |
| `ADDED` | `web/src/composables/useCsrf.ts` |
| `ADDED` | `web/src/composables/useMockChat.ts` |
| `ADDED` | `web/src/composables/useModels.ts` |
| `ADDED` | `web/src/composables/useUserSession.ts` |
| `ADDED` | `web/src/layouts/default.vue` |
| `ADDED` | `web/src/main.ts` |
| `ADDED` | `web/src/mock/errorMap.ts` |
| `ADDED` | `web/src/mock/mockAgent.ts` |
| `ADDED` | `web/src/mock/types.ts` |
| `ADDED` | `web/src/nuxt-ui-globals.d.ts` |
| `ADDED` | `web/src/pages/chat/[id].vue` |
| `ADDED` | `web/src/pages/index.vue` |
| `ADDED` | `web/src/route-map.d.ts` |
| `ADDED` | `web/src/utils/ai.ts` |
| `ADDED` | `web/src/utils/tool.ts` |
| `ADDED` | `web/src/utils/url.ts` |
| `ADDED` | `web/src/vite-env.d.ts` |
| `ADDED` | `web/tsconfig.app.json` |
| `ADDED` | `web/tsconfig.json` |
| `ADDED` | `web/tsconfig.node.json` |
| `ADDED` | `web/vite.config.ts` |

## 4. Git Commit Verification Log
| Short Hash | Author | Date | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `66c976717` | cheng-sh | 2026-06-26 | `Feature` | Add web files from HTC-web |

---
## 5. Next Sprint Outlook
- Continue integration and refinement based on cross-module milestones.
- Address feedback and optimize test coverage for modified files.
