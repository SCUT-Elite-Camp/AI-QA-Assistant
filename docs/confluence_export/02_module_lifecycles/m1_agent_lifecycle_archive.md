# Agent Module (Orchestration & Reasoning) - Complete Lifecycle Archive

> **Module Key**: `agent` | **Root Directory**: `/agent`
> **Total Lifetime Commits**: `49` | **Contributors**: Ivan, Tao, YourGitHubUsername, fionaxi, mgy2006@outlook.com

---

## 1. Module Description & Responsibilities
Core LLM orchestration, multi-turn dialogue management, streaming SSE protocol, and reasoning logic.

## 2. Sprint-by-Sprint Evolution
| Sprint | Date Range | Commits | Deliverables Highlights |
| :--- | :--- | :--- | :--- |
| **2026-W23** | 2026-06-05 ~ 2026-06-05 | 1 | Initialize project skeleton structure |
| **2026-W24** | - | 0 | *Maintenance / Idle* |
| **2026-W25** | 2026-06-17 ~ 2026-06-17 | 1 | Create .gitkeep |
| **2026-W26** | 2026-06-22 ~ 2026-06-22 | 1 | feat(agent): add week2 rag integration |
| **2026-W27** | 2026-06-29 ~ 2026-07-05 | 14 | feat(agent): sync week3 quality controls; feat(agent): complete q1 week4 handoff |
| **2026-W28** | 2026-07-09 ~ 2026-07-10 | 3 | feat(agent): integrate local Ollama qwen2.5:14b via OpenAI-compatible API; fix(agent): rewrite run() to proper RAG flow to fix NO_RELEVANT_CONTEXT |
| **2026-W30** | 2026-07-20 ~ 2026-07-25 | 9 | system update; feat: add agent tool registry |
| **2026-W31** | 2026-07-27 ~ 2026-08-02 | 8 | feat: align cp2 query contracts and routing; feat: add structured tool executor |
| **2026-W32** | 2026-08-03 ~ 2026-08-07 | 3 | feat(data-process): upgrade data processing pipeline; feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation |
| **2026-W33** | 2026-08-11 ~ 2026-08-11 | 1 | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
| **2026-W34** | 2026-08-18 ~ 2026-08-18 | 8 | feat: implement real token-by-token LLM streaming and full reasoning_content thinking chain; fix: construct Citation instances directly from evidence in streaming endpoint |

## 3. All Historical Commits for this Module
| Short Hash | Date | Author | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `65cf2366a` | 2026-06-05 | YourGitHubUsername | `Maintenance / Chore` | Initialize project skeleton structure |
| `73252593d` | 2026-06-17 | Tao | `Maintenance / Chore` | Create .gitkeep |
| `61f91e885` | 2026-06-22 | Ivan | `Feature` | feat(agent): add week2 rag integration |
| `21f7a308e` | 2026-06-29 | Ivan | `Feature` | feat(agent): sync week3 quality controls |
| `2b1350a1d` | 2026-07-03 | Ivan | `Feature` | feat(agent): complete q1 week4 handoff |
| `0c9933872` | 2026-07-04 | YourGitHubUsername | `Feature` | feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |
| `53217c7fb` | 2026-07-04 | YourGitHubUsername | `Feature` | feat: make MockLLM dynamic by reading prompt context and generating realistic answers |
| `54a97a3df` | 2026-07-04 | YourGitHubUsername | `Bug Fix` | fix: adjust MockLLM parser to handle colon-separated fields from ContextAssembler |
| `cd0add9a2` | 2026-07-04 | YourGitHubUsername | `Feature` | feat: return raw retrieval context directly in MockLLM |
| `64b357c8b` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: optimize project structures, decouple modules, remove redundant code across all layers |
| `539e24d91` | 2026-07-05 | YourGitHubUsername | `Feature` | feat: implement SQLite chat history audit logging store and GET history API endpoint |
| `d03fa544d` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: replace single-turn RAG with autonomous Agent Loop, remove RetrievalAdapter & MockLLM, rewrite unit tests with standard mocks |
| `5b33d37ed` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: delete service folder, place agent.py directly in agent package root, rename unit test to test_agent.py |
| `3dd3fef78` | 2026-07-05 | YourGitHubUsername | `Refactoring` | refactor: extract AOP auxiliary concerns into trace and audit services in service folder, call them within Agent run loop |
| `8136bebaa` | 2026-07-05 | YourGitHubUsername | `Maintenance / Chore` | chore: set default max_iterations to 1 in Agent run() |
| `64e76cc78` | 2026-07-05 | YourGitHubUsername | `Feature` | feat: support bypass_llm setting in Agent to directly return tool search outcomes, disable bypass in tests |
| `43c9c75eb` | 2026-07-05 | YourGitHubUsername | `Bug Fix` | fix: inject project folders into sys.path in app.py to prevent ModuleNotFoundErrors when running server directly |
| `b56957250` | 2026-07-09 | YourGitHubUsername | `Feature` | feat(agent): integrate local Ollama qwen2.5:14b via OpenAI-compatible API |
| `1739c6004` | 2026-07-09 | YourGitHubUsername | `Bug Fix` | fix(agent): rewrite run() to proper RAG flow to fix NO_RELEVANT_CONTEXT |
| `32a1bfc45` | 2026-07-10 | YourGitHubUsername | `Bug Fix` | fix: display tooltip below badge and send full citation snippet from backend |
| `1e4d97ed3` | 2026-07-20 | YourGitHubUsername | `Maintenance / Chore` | system update |
| `42376c860` | 2026-07-24 | fionaxi | `Feature` | feat: add agent tool registry |
| `32559e07a` | 2026-07-25 | fionaxi | `Feature` | feat: add query rewriter |
| `e93c32fbf` | 2026-07-25 | fionaxi | `Feature` | feat: add clarification decision |
| `d9fa78df1` | 2026-07-25 | fionaxi | `Bug Fix` | fix: use toolset registry adapter |
| `9a974d720` | 2026-07-25 | fionaxi | `Feature` | feat: define query plan contract |
| `0249936ee` | 2026-07-25 | fionaxi | `Documentation` | docs: organize cp1 and cp2 documentation |
| `480b89944` | 2026-07-25 | fionaxi | `Documentation` | docs: translate cp2 contracts to English |
| `3d3f27dda` | 2026-07-25 | fionaxi | `Feature` | feat: add intent classifier |
| `b555c8db1` | 2026-07-27 | fionaxi | `Feature` | feat: align cp2 query contracts and routing |
| `ce26046c2` | 2026-07-28 | fionaxi | `Feature` | feat: add structured tool executor |
| `145f085e7` | 2026-07-28 | fionaxi | `Feature` | feat: add cp2 evidence quality controls |
| `c48dc9fbb` | 2026-07-28 | fionaxi | `Feature` | feat: add query planning enrichment |
| `e51fee3e5` | 2026-07-29 | fionaxi | `Documentation` | docs: refresh cp2 unit test report |
| `f16ef8552` | 2026-07-30 | Ivan | `Feature` | feat(agent): integrate CP2 memory and bounded runner |
| `f72968339` | 2026-07-30 | Ivan | `Documentation` | docs(agent): record merged CP2 verification baseline |
| `70b8c3b2c` | 2026-08-02 | Ivan | `Feature` | feat(agent): orchestrate CP2 components in chat flow |
| `ba1a6cc07` | 2026-08-03 | mgy2006@outlook.com | `Feature` | feat(data-process): upgrade data processing pipeline |
| `ae1a13871` | 2026-08-05 | YourGitHubUsername | `Feature` | feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation |
| `80f3e4462` | 2026-08-07 | YourGitHubUsername | `Feature` | feat: complete topic management, dialogue branching, multi-turn chat, data persistence, and integrate remote dev |
| `5cdccce39` | 2026-08-11 | YourGitHubUsername | `Feature` | feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout |
| `094ee4b00` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: implement real token-by-token LLM streaming and full reasoning_content thinking chain |
| `61d1ceec8` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: construct Citation instances directly from evidence in streaming endpoint |
| `121df91ff` | 2026-08-18 | YourGitHubUsername | `Feature` | fix: add message argument to ChatResponse in streaming endpoint |
| `747effd5e` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: use runner._execute_tool in streaming endpoint for correct keyword argument dispatch |
| `f295ed9ee` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: pass keyword arguments to _save_conversation_turn in streaming endpoint |
| `7db171493` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: import Citation in chat_routes and improve SSE stream error handling in post.ts |
| `562658c32` | 2026-08-18 | YourGitHubUsername | `Bug Fix` | fix: safely extract evidence fields from dict or object in Citations building |
| `d12c92e79` | 2026-08-18 | YourGitHubUsername | `Feature` | feat: switch mode selector to Auto, Fast, and Thinking with Thinking as current default |
