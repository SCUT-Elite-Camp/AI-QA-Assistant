# Web Module (UI & Full-stack Gateway) - Complete Lifecycle Archive

> **Module Key**: `web` | **Root Directory**: `/web`
> **Total Lifetime Commits**: `33` | **Contributors**: Tao, YourGitHubUsername, cheng-sh

---

## 1. Module Description & Responsibilities
Frontend UI components, chat view, document viewer, settings drawer, and server-side API proxy.

## 2. Sprint-by-Sprint Evolution
| Sprint | Date Range | Commits | Deliverables Highlights |
| :--- | :--- | :--- | :--- |
| **2026-W23** | - | 0 | *Maintenance / Idle* |
| **2026-W24** | - | 0 | *Maintenance / Idle* |
| **2026-W25** | 2026-06-17 ~ 2026-06-17 | 1 | Create web/.gitkeep |
| **2026-W26** | 2026-06-26 ~ 2026-06-26 | 1 | Add web files from HTC-web |
| **2026-W27** | 2026-07-03 ~ 2026-07-04 | 2 | feat(web): add e2e tests, english error messages, and playwright config; feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |
| **2026-W28** | 2026-07-09 ~ 2026-07-10 | 5 | feat(web): inline cite-mark tooltips + deduplicated sources panel; fix(web): fix cite-mark MDC parse failure + clean circle design |
| **2026-W30** | 2026-07-20 ~ 2026-07-26 | 3 | system update; feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring |
| **2026-W31** | - | 0 | *Maintenance / Idle* |
| **2026-W32** | 2026-08-05 ~ 2026-08-07 | 2 | feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation; feat: complete topic management, dialogue branching, multi-turn chat, data persistence, and integrate remote dev |
| **2026-W33** | 2026-08-11 ~ 2026-08-11 | 1 | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
| **2026-W34** | 2026-08-18 ~ 2026-08-21 | 18 | style: simplify HitRateDrawer turn cards and sort latest turns at top; style: simplify progress indicator to real SSE event status text and minimal clean document bar |

## 3. All Historical Commits for this Module
| Short Hash | Date | Author | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `cc9070af9` | 2026-06-17 | Tao | `Maintenance / Chore` | Create web/.gitkeep |
| `66c976717` | 2026-06-26 | cheng-sh | `Feature` | Add web files from HTC-web |
| `d689c50e1` | 2026-07-03 | cheng-sh | `Feature` | feat(web): add e2e tests, english error messages, and playwright config |
| `0c9933872` | 2026-07-04 | YourGitHubUsername | `Feature` | feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |
| `6be2c3d45` | 2026-07-09 | YourGitHubUsername | `Feature` | feat(web): inline cite-mark tooltips + deduplicated sources panel |
| `5517f5376` | 2026-07-09 | YourGitHubUsername | `Bug Fix` | fix(web): fix cite-mark MDC parse failure + clean circle design |
| `70621a418` | 2026-07-09 | YourGitHubUsername | `Bug Fix` | fix(web/CiteMark): match neutral/outline style, fixed-position scrollable tooltip |
| `63c7e7679` | 2026-07-10 | YourGitHubUsername | `Bug Fix` | fix(web): fix MDC parser rendering issue by prepending space to inline components |
| `32a1bfc45` | 2026-07-10 | YourGitHubUsername | `Bug Fix` | fix: display tooltip below badge and send full citation snippet from backend |
| `1e4d97ed3` | 2026-07-20 | YourGitHubUsername | `Maintenance / Chore` | system update |
| `a9c20c7f9` | 2026-07-26 | cheng-sh | `Feature` | feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring |
| `40637f220` | 2026-07-26 | cheng-sh | `Feature` | feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring |
| `ae1a13871` | 2026-08-05 | YourGitHubUsername | `Feature` | feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation |
| `80f3e4462` | 2026-08-07 | YourGitHubUsername | `Feature` | feat: complete topic management, dialogue branching, multi-turn chat, data persistence, and integrate remote dev |
| `5cdccce39` | 2026-08-11 | YourGitHubUsername | `Feature` | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
| `2abd58cd9` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | style: simplify HitRateDrawer turn cards and sort latest turns at top |
| `5503b341a` | 2026-08-18 | YourGitHubUsername | `Refactoring` | style: simplify progress indicator to real SSE event status text and minimal clean document bar |
| `65d030352` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | revert: restore original Sources.vue chunk display layout |
| `006a0e6cc` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: real-time streaming state tracking for ProgressIndicator |
| `e4fa052a3` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: remove all timers and fake estimations from ProgressIndicator, 100% SSE event driven |
| `78e0e9687` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: scope ProgressIndicator assistant message strictly to current turn |
| `854ff4b82` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: stream tool-input-available immediately before agent retrieval for real-time SSE progress |
| `094ee4b00` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: implement real token-by-token LLM streaming and full reasoning_content thinking chain |
| `7db171493` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: import Citation in chat_routes and improve SSE stream error handling in post.ts |
| `e221e00a3` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | style: remove question suffix from tool trigger and enlarge font size for tool and reasoning trigger text |
| `dec8ade0a` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: place Thought duration collapsible on the left of 已检索知识库 on the same row |
| `1e1535ac4` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: layout Thought for Xs on the right of 已检索知识库 on same line with collapsible toggle and duration display |
| `d12c92e79` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: switch mode selector to Auto, Fast, and Thinking with Thinking as current default |
| `776766108` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | style: remove icons from mode selector menu and keep pure text labels |
| `9c5d0e54f` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | style: remove hit rate monitoring button and banner from quick navigation dial |
| `41119e949` | 2026-08-18 | YourGitHubUsername | `UI / Style Enhancement` | style: remove hash prefix from quick nav buttons and keep pure numbers |
| `c251af965` | 2026-08-21 | YourGitHubUsername | `Feature` | feat: implement Grok-style progressive step-by-step reasoning tree and timeline feedback |
| `eee89ab42` | 2026-08-21 | YourGitHubUsername | `Bug Fix` | fix: template string expressions in ThinkingProcess.vue |
