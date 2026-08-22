# 06b Agent Memory 与冻结 Runtime 的人工对齐

## 目标

把旧 `web-dev` 提交中已实现的 Agent Memory 行为作为参考，逐文件适配到冻结的 `origin/agent-dev-infra@5955cd0`。本单元解决的是 Runtime 结构变化后的兼容性，不新增 Snapshot、Fact、Tail、Redis、Research 或公开 API 功能。旧分支的测试结果不能替代本单元的新版 Runtime 验收。

前置：`04`、`04a`、`05`、`06a`。负责人：持有 Agent 热点写锁的集成人。后续：`06`、`07`、`08`。

## 输入、输出与非目标

输入：

- 冻结工作目录 `D:\project\AI-QA-Assistant-agent-memory` 的干净 `agent-dev-infra`：`5955cd0` 必须是 HEAD 的祖先，开始 Memory 代码迁移前其后的差异仅可为本目录的 docs-only 同步提交，或已独立验证、仅修改 `agent/requirements-week1.txt` 的可复现性修复；
- 旧实现参考 `web-dev@e303544`、`web-dev@8048e90`；
- 已锁定的内部 DTO/token 契约及 Web BFF `memory_context` 结构。

输出：在新的 Agent 基线上得到与原 01--08 相同的内部 Memory 契约、Resolver、Prompt/Recall、Compaction 和 reset 能力，并明确每个改动相对冻结 Runtime 的合并方式。

非目标：不迁移 Web 文件、migration、Redis、USER Fact、自动确认、Fact lifecycle、UI；不采用 `feat/permission-hardening` 的 Bearer 鉴权；不接入 Deep Research。

## 文件迁移矩阵

| 类别 | 文件/路径 | 处理方式 |
| --- | --- | --- |
| 可新增 | `agent/agent/memory/context_resolver.py`、`memory_response_policy.py`、`compaction_planner.py`、`persistent_models.py` | 从旧实现逐个复制逻辑后，按 `5955` 的 DTO/import 审查 |
| 可新增 | `agent/agent/api/internal_memory_routes.py`、对应新增 unit/integration tests | 新建；内部依赖必须复用 `get_agent()` |
| 人工三方合并 | `agent.py`、`api/chat_routes.py`、`config/settings.py`、`orchestration/orchestrator.py`、`runtime/runner.py`、`schemas/chat.py`、`app.py`、`.env.example`、API contract 与既有测试 | 以 `5955` 为主，按本计划重新引入最小 Memory 改动 |
| 保持冻结 | `runtime/lifecycle.py`、`tools/executor.py` | 不从旧分支覆盖，不为 Memory 重构 |
| 禁止触碰 | `agent/deep_research/**`、所有 `web/**` | Chat Memory 不得耦合研究运行时或 Web 数据层 |

## 施工步骤

### 1. 基线和差异清点

在 Agent Memory 工作目录中确认 `06a` 的 hash、工作区状态和最终调用链。以 `git diff 5955cd0..web-dev -- agent/` 生成候选文件清单，但只按上表选择文件；不要 cherry-pick `8048e90`。

停止条件：存在未归属的热点改动、基线不为 `5955cd0`，或调用链不再经过共享 `get_agent()`。

### 2. 先恢复数据契约与开关

以 `5955` 的 `schemas/chat.py` 和 `config/settings.py` 为主，人工增加内部 `memory_context`、`InternalChatResponse`、compaction/reset DTO 与 `PERSISTENT_MEMORY_ENABLED` 等既定开关。默认必须关闭；公开 Chat request/response 不得增加 Memory 字段。

路由鉴权仍使用 `X-Agent-Internal-Token`：缺失/错误为 403，持久 Memory 关闭为 409。不得将该单元偷偷替换成 Bearer scope。

### 3. 适配 ApplicationContainer 与内部路由

保留 `app.py` 的 lifespan、`ApplicationContainer`、warm-up 和 `/ready`。在 app 中注册内部 Memory router，但 router 的 Agent 依赖必须导入并复用 `api/chat_routes.py:get_agent()`。不得创建第二个全局 Agent，也不得重写 `runtime/lifecycle.py`。

通过 dependency override 测试证明普通 Chat 与内部 Memory endpoint 使用同一可替换依赖。

### 4. 适配 Resolve、Prompt 与 Recall

添加纯 Memory 模块并在 `orchestrator.py` 接收 BFF 信任边界内的 `memory_context`。在 `runner.py` 的当前 `_build_messages()` 接入：基础/RAG system rules、Memory system context、Tail/history、当前 query 一次。`5955` 现有 system prompt 会直接包含 standalone query；若它等于 original query，必须去除这份重复原文，并新增全 messages 范围的回归断言。保留其余工具循环、QueryPlan 和 citation 流程。

`MemoryResponsePolicy` 只能消费已解析的 Confirmed Facts；普通问题不触发。`fact_proposals` 在 01--08 中始终返回空数组，由 `09` 独占生成与生命周期。

### 5. 适配压缩与短窗 reset

新增纯 `CompactionPlanner` 与内部 endpoint。仅在 Web 已持久化成功助手消息后由 BFF 调用；Planner 不访问 DB、不调用 LLM、不创建后台队列。reset endpoint 同样从共享 `get_agent()` 取得实例，仅清旧短窗兼容状态，不触碰持久 Snapshot/Fact。

### 6. 交叉验证和交接

运行冻结 Runtime 的 Week-1 测试、所有新增 Memory 测试和 12 的跨层证据。逐项记录迁移文件、保留的 `5955` 行为、契约差异（应为无公开差异）和无法验证项。

## 必须通过的不变量

- 默认开关关闭时维持 `5955` 的 Chat 行为；
- 一个 HTTP 请求只从共享 `ApplicationContainer` 获得一个 Agent 实例，不新增全局实例；
- BFF 是 ChatMessage/Snapshot/Fact 的唯一数据库写入者；Agent 只消费可信 DTO、返回纯计划；
- 当前 query 在最终模型 messages 中出现一次；Fact 不是 citation；
- 内部 token 负向测试为 403，开关关闭为 409；
- Chat 和所有 Memory endpoint 不创建、读取或修改 Deep Research Job/状态。

## 建议命令与证据

```powershell
git -C D:\project\AI-QA-Assistant-agent-memory status --short --branch
git -C D:\project\AI-QA-Assistant-agent-memory show --no-patch --format=%H HEAD
rg -n "get_application_container|ApplicationContainer|def get_agent|def _build_messages|llm\.chat" D:\project\AI-QA-Assistant-agent-memory\agent
```

测试命令以冻结分支实际提供的 runner 为准；至少包含该 runner 的 Week-1 回归、Memory 目标 pytest、以及 `12` 的跨层验证。命令、环境、通过/失败数必须进入交接；不可运行时明确写未运行和原因。

## 完成条件

所有迁移文件均已按矩阵审查，`runtime/lifecycle.py`、`tools/executor.py`、`deep_research/**` 和 Web 文件未被 Memory 改动；`06` 的 Prompt/Recall 测试、容器复用测试和 Chat/Research 隔离测试通过。否则停止在本单元，不进入 `06`、`07` 或 `08`。
