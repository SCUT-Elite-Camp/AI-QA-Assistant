# Release Changelog & Artifacts Archive

> **Project Changelog**: Master historical record of features and fixes.

---

## Full Chronological Changelog
### Sprint 2026-W34 (2026-08-18 ~ 2026-08-21)
**Total Commits**: 23

- `[UI / Style Enhancement]` **style: simplify HitRateDrawer turn cards and sort latest turns at top** (`2abd58cd9` by @YourGitHubUsername)
- `[Refactoring]` **style: simplify progress indicator to real SSE event status text and minimal clean document bar** (`5503b341a` by @YourGitHubUsername)
- `[UI / Style Enhancement]` **revert: restore original Sources.vue chunk display layout** (`65d030352` by @YourGitHubUsername)
- `[Bug Fix]` **fix: real-time streaming state tracking for ProgressIndicator** (`006a0e6cc` by @YourGitHubUsername)
- `[Bug Fix]` **fix: remove all timers and fake estimations from ProgressIndicator, 100% SSE event driven** (`e4fa052a3` by @YourGitHubUsername)
- `[Bug Fix]` **fix: scope ProgressIndicator assistant message strictly to current turn** (`78e0e9687` by @YourGitHubUsername)
- `[Feature]` **feat: stream tool-input-available immediately before agent retrieval for real-time SSE progress** (`854ff4b82` by @YourGitHubUsername)
- `[Feature]` **feat: implement real token-by-token LLM streaming and full reasoning_content thinking chain** (`094ee4b00` by @YourGitHubUsername)
- `[Bug Fix]` **fix: construct Citation instances directly from evidence in streaming endpoint** (`61d1ceec8` by @YourGitHubUsername)
- `[Feature]` **fix: add message argument to ChatResponse in streaming endpoint** (`121df91ff` by @YourGitHubUsername)
- `[Bug Fix]` **fix: use runner._execute_tool in streaming endpoint for correct keyword argument dispatch** (`747effd5e` by @YourGitHubUsername)
- `[Bug Fix]` **fix: pass keyword arguments to _save_conversation_turn in streaming endpoint** (`f295ed9ee` by @YourGitHubUsername)
- `[Bug Fix]` **fix: import Citation in chat_routes and improve SSE stream error handling in post.ts** (`7db171493` by @YourGitHubUsername)
- `[Bug Fix]` **fix: safely extract evidence fields from dict or object in Citations building** (`562658c32` by @YourGitHubUsername)
- `[UI / Style Enhancement]` **style: remove question suffix from tool trigger and enlarge font size for tool and reasoning trigger text** (`e221e00a3` by @YourGitHubUsername)
- `[Feature]` **feat: place Thought duration collapsible on the left of 已检索知识库 on the same row** (`dec8ade0a` by @YourGitHubUsername)
- `[Feature]` **feat: layout Thought for Xs on the right of 已检索知识库 on same line with collapsible toggle and duration display** (`1e1535ac4` by @YourGitHubUsername)
- `[Feature]` **feat: switch mode selector to Auto, Fast, and Thinking with Thinking as current default** (`d12c92e79` by @YourGitHubUsername)
- `[UI / Style Enhancement]` **style: remove icons from mode selector menu and keep pure text labels** (`776766108` by @YourGitHubUsername)
- `[UI / Style Enhancement]` **style: remove hit rate monitoring button and banner from quick navigation dial** (`9c5d0e54f` by @YourGitHubUsername)
- `[UI / Style Enhancement]` **style: remove hash prefix from quick nav buttons and keep pure numbers** (`41119e949` by @YourGitHubUsername)
- `[Feature]` **feat: implement Grok-style progressive step-by-step reasoning tree and timeline feedback** (`c251af965` by @YourGitHubUsername)
- `[Bug Fix]` **fix: template string expressions in ThinkingProcess.vue** (`eee89ab42` by @YourGitHubUsername)

### Sprint 2026-W33 (2026-08-11 ~ 2026-08-11)
**Total Commits**: 1

- `[Feature]` **feat: add Hit Rate & Similarity monitoring drawer, optimize agent streaming resilience and UI navbar layout** (`5cdccce39` by @YourGitHubUsername)

### Sprint 2026-W32 (2026-08-03 ~ 2026-08-07)
**Total Commits**: 10

- `[Feature]` **feat(data-process): upgrade data processing pipeline** (`ba1a6cc07` by @mgy2006@outlook.com)
- `[Feature]` **feat(toolset): add fail-open query enhancement** (`08710bf81` by @unknown)
- `[Maintenance / Chore]` **Merge pull request #16 from SCUT-Elite-Camp/feat/web-observability** (`5af5fd956` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #18 from SCUT-Elite-Camp/toolset** (`57d110c68` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #19 from SCUT-Elite-Camp/agent-dev** (`de9c91c8e` by @YKASN)
- `[Feature]` **feat: multi-turn chat, data persistence, doc parser, markdown rendering, and auto title generation** (`ae1a13871` by @YourGitHubUsername)
- `[Feature]` **feat(data-pipeline): add Confluence HTML & attachment crawler** (`f818fddd1` by @钟家进)
- `[Maintenance / Chore]` **Merge pull request #20 from SCUT-Elite-Camp/feat/confluence-html-attachment-pipeline** (`4c7109cd5` by @YKASN)
- `[Maintenance / Chore]` **Merge remote origin/dev into optimization** (`24a50e360` by @YourGitHubUsername)
- `[Feature]` **feat: complete topic management, dialogue branching, multi-turn chat, data persistence, and integrate remote dev** (`80f3e4462` by @YourGitHubUsername)

### Sprint 2026-W31 (2026-07-27 ~ 2026-08-02)
**Total Commits**: 12

- `[Feature]` **feat: align cp2 query contracts and routing** (`b555c8db1` by @fionaxi)
- `[Feature]` **feat: add structured tool executor** (`ce26046c2` by @fionaxi)
- `[Feature]` **feat: add cp2 evidence quality controls** (`145f085e7` by @fionaxi)
- `[Feature]` **feat: add query planning enrichment** (`c48dc9fbb` by @fionaxi)
- `[Documentation]` **docs: refresh cp2 unit test report** (`e51fee3e5` by @fionaxi)
- `[Feature]` **feat(agent): integrate CP2 memory and bounded runner** (`f16ef8552` by @Ivan)
- `[Maintenance / Chore]` **merge: integrate CP2 query understanding and evidence controls** (`9853af91f` by @Ivan)
- `[Maintenance / Chore]` **merge: complete CP2 agent runtime integration** (`bd08cd34b` by @Ivan)
- `[Documentation]` **docs(agent): record merged CP2 verification baseline** (`f72968339` by @Ivan)
- `[Feature]` **feat(toolset): add English BM25 and reranking** (`be392bc32` by @unknown)
- `[Feature]` **feat(agent): orchestrate CP2 components in chat flow** (`70b8c3b2c` by @Ivan)
- `[Feature]` **feat(data-pipeline): add knowledge cards, precompressor, segmenter, and benchmark modules** (`f4f6d7a03` by @mgy2006@outlook.com)

### Sprint 2026-W30 (2026-07-20 ~ 2026-07-26)
**Total Commits**: 14

- `[Maintenance / Chore]` **system update** (`1e4d97ed3` by @YourGitHubUsername)
- `[Maintenance / Chore]` **chore: update .gitignore to exclude node_modules, venv and volumes** (`0db3046ec` by @YourGitHubUsername)
- `[Maintenance / Chore]` **merge: bring all completed project features from dev into data-persistence-dev** (`a8f0cbff8` by @YourGitHubUsername)
- `[Maintenance / Chore]` **Merge pull request #15 from SCUT-Elite-Camp/data-persistence-dev** (`61e9dbc08` by @YKASN)
- `[Feature]` **feat: add agent tool registry** (`42376c860` by @fionaxi)
- `[Feature]` **feat: add query rewriter** (`32559e07a` by @fionaxi)
- `[Feature]` **feat: add clarification decision** (`e93c32fbf` by @fionaxi)
- `[Bug Fix]` **fix: use toolset registry adapter** (`d9fa78df1` by @fionaxi)
- `[Feature]` **feat: define query plan contract** (`9a974d720` by @fionaxi)
- `[Documentation]` **docs: organize cp1 and cp2 documentation** (`0249936ee` by @fionaxi)
- `[Documentation]` **docs: translate cp2 contracts to English** (`480b89944` by @fionaxi)
- `[Feature]` **feat: add intent classifier** (`3d3f27dda` by @fionaxi)
- `[Feature]` **feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring** (`a9c20c7f9` by @cheng-sh)
- `[Feature]` **feat(web): add observability dashboard, metrics endpoint, trace ID, and Web Vitals monitoring** (`40637f220` by @cheng-sh)

### Sprint 2026-W28 (2026-07-06 ~ 2026-07-10)
**Total Commits**: 9

- `[Maintenance / Chore]` **Merge pull request #14 from SCUT-Elite-Camp/optimization** (`a61bfa4c9` by @YKASN)
- `[Feature]` **feat(agent): integrate local Ollama qwen2.5:14b via OpenAI-compatible API** (`b56957250` by @YourGitHubUsername)
- `[Bug Fix]` **fix(start): stop overwriting agent/.env with USE_MOCK_LLM=true on every launch** (`22953c05f` by @YourGitHubUsername)
- `[Bug Fix]` **fix(agent): rewrite run() to proper RAG flow to fix NO_RELEVANT_CONTEXT** (`1739c6004` by @YourGitHubUsername)
- `[Feature]` **feat(web): inline cite-mark tooltips + deduplicated sources panel** (`6be2c3d45` by @YourGitHubUsername)
- `[Bug Fix]` **fix(web): fix cite-mark MDC parse failure + clean circle design** (`5517f5376` by @YourGitHubUsername)
- `[Bug Fix]` **fix(web/CiteMark): match neutral/outline style, fixed-position scrollable tooltip** (`70621a418` by @YourGitHubUsername)
- `[Bug Fix]` **fix(web): fix MDC parser rendering issue by prepending space to inline components** (`63c7e7679` by @YourGitHubUsername)
- `[Bug Fix]` **fix: display tooltip below badge and send full citation snippet from backend** (`32a1bfc45` by @YourGitHubUsername)

### Sprint 2026-W27 (2026-06-29 ~ 2026-07-05)
**Total Commits**: 35

- `[Feature]` **feat: 数据处理管线 - embedder增强、文档和脚本** (`41b6c23a9` by @mgy2006@outlook.com)
- `[Maintenance / Chore]` **merge: 合并远程 data-pipeline，解决冲突** (`581817889` by @mgy2006@outlook.com)
- `[Feature]` **feat(agent): sync week3 quality controls** (`21f7a308e` by @Ivan)
- `[Feature]` **feat(toolset): add CP3 logging and evaluation** (`43edacac8` by @unknown)
- `[Feature]` **Add @YKASN to CODEOWNERS** (`3fab95b73` by @Tao)
- `[Feature]` **Add @scutnobody as a code owner** (`0070aad6a` by @Tao)
- `[Feature]` **feat(web): add e2e tests, english error messages, and playwright config** (`d689c50e1` by @cheng-sh)
- `[Feature]` **feat: add CP4 agent integration** (`e3d584965` by @CodexSandboxOffline)
- `[UI / Style Enhancement]` **docs: update CP4 toolset requirements** (`2f65cd460` by @CodexSandboxOffline)
- `[Feature]` **feat(agent): complete q1 week4 handoff** (`2b1350a1d` by @Ivan)
- `[Feature]` **feat: import docs, parsers, pipeline, retrieval from data-pipeline branch** (`4a136b45c` by @JiajinZhong77)
- `[Maintenance / Chore]` **Merge pull request #10 from SCUT-Elite-Camp/add-data-pipeline-modules** (`09c8aea71` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #11 from SCUT-Elite-Camp/toolset** (`3b0cf3950` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #6 from SCUT-Elite-Camp/agent-dev** (`0a996b6bf` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #7 from SCUT-Elite-Camp/data-persistence-dev** (`6f7541030` by @YKASN)
- `[Maintenance / Chore]` **Merge pull request #12 from SCUT-Elite-Camp/web** (`c31ca6e2a` by @YKASN)
- `[Feature]` **feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format** (`0c9933872` by @YourGitHubUsername)
- `[Feature]` **feat: make MockLLM dynamic by reading prompt context and generating realistic answers** (`53217c7fb` by @YourGitHubUsername)
- `[Bug Fix]` **fix: adjust MockLLM parser to handle colon-separated fields from ContextAssembler** (`54a97a3df` by @YourGitHubUsername)
- `[Bug Fix]` **fix: point documents_dir to data-persistence folder under milvus backend** (`441647077` by @YourGitHubUsername)
- `[Feature]` **feat: return raw retrieval context directly in MockLLM** (`cd0add9a2` by @YourGitHubUsername)
- `[Refactoring]` **refactor: abstract high-level DocumentParser class in data-pipeline parsers** (`8f804f099` by @YourGitHubUsername)
- `[Refactoring]` **refactor: optimize project structures, decouple modules, remove redundant code across all layers** (`64b357c8b` by @YourGitHubUsername)
- `[Feature]` **feat: implement SQLite chat history audit logging store and GET history API endpoint** (`539e24d91` by @YourGitHubUsername)
- `[Refactoring]` **refactor: replace single-turn RAG with autonomous Agent Loop, remove RetrievalAdapter & MockLLM, rewrite unit tests with standard mocks** (`d03fa544d` by @YourGitHubUsername)
- `[Refactoring]` **refactor: delete service folder, place agent.py directly in agent package root, rename unit test to test_agent.py** (`5b33d37ed` by @YourGitHubUsername)
- `[Refactoring]` **refactor: extract AOP auxiliary concerns into trace and audit services in service folder, call them within Agent run loop** (`3dd3fef78` by @YourGitHubUsername)
- `[Refactoring]` **refactor: simplify search_tool.py, delete redundant SearchBackend ABC and inheritances** (`7704c424c` by @YourGitHubUsername)
- `[Refactoring]` **refactor: delete LocalJsonlSearchBackend and its unused helper functions, delete associated unit tests** (`9c49e4942` by @YourGitHubUsername)
- `[Refactoring]` **refactor: keep retrieval execution logic inside toolset search_tool, do not pollute data-persistence or data-pipeline** (`83de3a02f` by @YourGitHubUsername)
- `[Refactoring]` **refactor: move retrieval package from data-pipeline to toolset, ensure data-pipeline is clean of retrieval logic** (`a7396869b` by @YourGitHubUsername)
- `[Maintenance / Chore]` **chore: set default max_iterations to 1 in Agent run()** (`8136bebaa` by @YourGitHubUsername)
- `[Feature]` **feat: support bypass_llm setting in Agent to directly return tool search outcomes, disable bypass in tests** (`64e76cc78` by @YourGitHubUsername)
- `[Bug Fix]` **fix: inject project folders into sys.path in app.py to prevent ModuleNotFoundErrors when running server directly** (`43c9c75eb` by @YourGitHubUsername)
- `[Testing & Evaluation]` **chore: remove unused retrieval evaluation module** (`d4dcba25d` by @YourGitHubUsername)

### Sprint 2026-W26 (2026-06-22 ~ 2026-06-26)
**Total Commits**: 5

- `[Feature]` **chore: add volumes/ to gitignore and remove from tracking** (`47945a216` by @mgy2006@outlook.com)
- `[Maintenance / Chore]` **首次提交项目代码** (`7988444ba` by @mgy2006@outlook.com)
- `[Feature]` **feat(toolset): implement CP2 hybrid retrieval** (`b3c4f0a62` by @unknown)
- `[Feature]` **feat(agent): add week2 rag integration** (`61f91e885` by @Ivan)
- `[Feature]` **Add web files from HTC-web** (`66c976717` by @cheng-sh)

### Sprint 2026-W25 (2026-06-16 ~ 2026-06-21)
**Total Commits**: 21

- `[Feature]` **feat: full-stack TS rewrite with AI SDK, Nuxt UI, Nitro, Drizzle** (`8005cf3c2` by @cheng-sh)
- `[Bug Fix]` **fix: remove .content from UIMessage, use parts-based text extraction** (`9d01363a5` by @cheng-sh)
- `[Bug Fix]` **fix: 对齐参考项目，修复输入框 Enter 提交和灰色问题** (`46be5e398` by @cheng-sh)
- `[Feature]` **feat: convert UI to English, fix mock agent keywords** (`a60787c81` by @cheng-sh)
- `[Feature]` **debug: add console logs and UI debug panel for message rendering** (`96ae87788` by @cheng-sh)
- `[Bug Fix]` **fix: 修复 useMockChat API 对齐 @ai-sdk/vue Chat 类** (`18826e915` by @cheng-sh)
- `[Maintenance / Chore]` **Initial commit** (`97e5cf47b` by @Tao)
- `[Maintenance / Chore]` **Create web/.gitkeep** (`cc9070af9` by @Tao)
- `[Maintenance / Chore]` **Merge pull request #1 from SCUT-Elite-Camp/tao-991-patch-1** (`44bebaf76` by @Tao)
- `[Maintenance / Chore]` **Create .gitkeep** (`73252593d` by @Tao)
- `[Maintenance / Chore]` **Merge pull request #2 from SCUT-Elite-Camp/tao-991-patch-2** (`7db180934` by @Tao)
- `[Maintenance / Chore]` **init monorepo structure** (`3c880814e` by @tao-991)
- `[Feature]` **chore: remove .DS_Store and add gitignore** (`87d8e82b7` by @tao-991)
- `[Feature]` **feat: finish the work of data persitence layer** (`890ad8fcc` by @YourGitHubUsername)
- `[Feature]` **feat: finish the work of data persitence layer** (`68b439cd1` by @YourGitHubUsername)
- `[Maintenance / Chore]` **chore: remove CODEOWNERS** (`7368879e6` by @tao-991)
- `[Maintenance / Chore]` **Merge pull request #4 from SCUT-Elite-Camp/dev** (`7145148da` by @Tao)
- `[Feature]` **chore: add CODEOWNERS for admin review** (`76fe28ddc` by @tao-991)
- `[Maintenance / Chore]` **Merge pull request #5 from SCUT-Elite-Camp/dev** (`5b014c5e1` by @Tao)
- `[Feature]` **feat: Simplify the file structure** (`537389eaa` by @YourGitHubUsername)
- `[Maintenance / Chore]` **Merge web repo into web/ subdirectory** (`7775454cd` by @cheng-sh)

### Sprint 2026-W24 (2026-06-09 ~ 2026-06-14)
**Total Commits**: 7

- `[UI / Style Enhancement]` **build up the Data Persistence Layer** (`70b6c3eb7` by @YourGitHubUsername)
- `[Maintenance / Chore]` **Merge branch 'main' of https://github.com/YKASN/RAGent** (`3a7d4b324` by @YourGitHubUsername)
- `[Documentation]` **Update Readme.md** (`56256817d` by @YourGitHubUsername)
- `[Feature]` **add doc_id in data persitence layer** (`55b743dee` by @YourGitHubUsername)
- `[Feature]` **feat: add AI assistant web layer MVP** (`59b9d906e` by @songsuijie)
- `[Maintenance / Chore]` **Initial commit** (`14d5c4cfe` by @songsuijie)
- `[Maintenance / Chore]` **chore: merge remote main history** (`ce3d98a5d` by @songsuijie)

### Sprint 2026-W23 (2026-06-05 ~ 2026-06-05)
**Total Commits**: 3

- `[Maintenance / Chore]` **Initialize project skeleton structure** (`65cf2366a` by @YourGitHubUsername)
- `[Documentation]` **Update Readme.md** (`014226995` by @YKASN)
- `[Documentation]` **Update Readme.md** (`cfd8f90c5` by @YKASN)

