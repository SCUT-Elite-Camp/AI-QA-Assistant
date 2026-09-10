# Toolset Module (Retrieval & Plugins) - Complete Lifecycle Archive

> **Module Key**: `toolset` | **Root Directory**: `/toolset`
> **Total Lifetime Commits**: `20` | **Contributors**: CodexSandboxOffline, YourGitHubUsername, mgy2006@outlook.com, tao-991, unknown

---

## 1. Module Description & Responsibilities
Knowledge base retrieval adapters, search tool integration, vector store connectors, and plugin tools.

## 2. Sprint-by-Sprint Evolution
| Sprint | Date Range | Commits | Deliverables Highlights |
| :--- | :--- | :--- | :--- |
| **2026-W23** | - | 0 | *Maintenance / Idle* |
| **2026-W24** | - | 0 | *Maintenance / Idle* |
| **2026-W25** | 2026-06-17 ~ 2026-06-17 | 1 | init monorepo structure |
| **2026-W26** | 2026-06-22 ~ 2026-06-22 | 1 | feat(toolset): implement CP2 hybrid retrieval |
| **2026-W27** | 2026-06-29 ~ 2026-07-05 | 11 | feat(toolset): add CP3 logging and evaluation; feat: add CP4 agent integration |
| **2026-W28** | - | 0 | *Maintenance / Idle* |
| **2026-W30** | 2026-07-20 ~ 2026-07-20 | 1 | system update |
| **2026-W31** | 2026-08-01 ~ 2026-08-01 | 1 | feat(toolset): add English BM25 and reranking |
| **2026-W32** | 2026-08-03 ~ 2026-08-07 | 4 | feat(data-process): upgrade data processing pipeline; feat(toolset): add fail-open query enhancement |
| **2026-W33** | 2026-08-11 ~ 2026-08-11 | 1 | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
| **2026-W34** | - | 0 | *Maintenance / Idle* |

## 3. All Historical Commits for this Module
| Short Hash | Date | Author | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `3c880814e` | 2026-06-17 | tao-991 | `Maintenance / Chore` | init monorepo structure |
| `b3c4f0a62` | 2026-06-22 | unknown | `Feature` | feat(toolset): implement CP2 hybrid retrieval |
| `43edacac8` | 2026-06-29 | unknown | `Feature` | feat(toolset): add CP3 logging and evaluation |
| `e3d584965` | 2026-07-03 | CodexSandboxOffline | `Feature` | feat: add CP4 agent integration |
| `2f65cd460` | 2026-07-03 | CodexSandboxOffline | `UI / Style Enhancement` | docs: update CP4 toolset requirements |
| `0c9933872` | 2026-07-04 | YourGitHubUsername | `Feature` | feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |
| `441647077` | 2026-07-04 | YourGitHubUsername | `Bug Fix` | fix: point documents_dir to data-persistence folder under milvus backend |
| `64b357c8b` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: optimize project structures, decouple modules, remove redundant code across all layers |
| `d03fa544d` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: replace single-turn RAG with autonomous Agent Loop, remove RetrievalAdapter & MockLLM, rewrite unit tests with standard mocks |
| `7704c424c` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: simplify search_tool.py, delete redundant SearchBackend ABC and inheritances |
| `9c49e4942` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: delete LocalJsonlSearchBackend and its unused helper functions, delete associated unit tests |
| `83de3a02f` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: keep retrieval execution logic inside toolset search_tool, do not pollute data-persistence or data-pipeline |
| `d4dcba25d` | 2026-07-05 | YourGitHubUsername | `Testing & Evaluation` | chore: remove unused retrieval evaluation module |
| `1e4d97ed3` | 2026-07-20 | YourGitHubUsername | `Maintenance / Chore` | system update |
| `be392bc32` | 2026-08-01 | unknown | `Feature` | feat(toolset): add English BM25 and reranking |
| `ba1a6cc07` | 2026-08-03 | mgy2006@outlook.com | `Feature` | feat(data-process): upgrade data processing pipeline |
| `08710bf81` | 2026-08-03 | unknown | `Feature` | feat(toolset): add fail-open query enhancement |
| `ae1a13871` | 2026-08-05 | YourGitHubUsername | `Feature` | feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation |
| `80f3e4462` | 2026-08-07 | YourGitHubUsername | `Feature` | feat: complete topic management, dialogue branching, multi-turn chat, data persistence, and integrate remote dev |
| `5cdccce39` | 2026-08-11 | YourGitHubUsername | `Feature` | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
