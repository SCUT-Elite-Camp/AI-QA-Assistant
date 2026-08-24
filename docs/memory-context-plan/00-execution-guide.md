# Persistent Memory 施工总控书

## 使用方式

本目录是一组可直接执行的施工单。任何 Agent 必须先读本文件，再严格按编号完成单元；一次只实施一个单元。完成一个单元后必须运行该文档列出的测试、检查工作区只包含允许的文件，并在 PR/交接信息中报告验收结果。没有通过验收不得开始下一单元。

本目录已经受 Git 跟踪；其源文件首先在 `web-dev` 维护，并必须以经审查的 docs-only
提交同步到唯一 Agent 开发线，随后才可实施任何 Agent Memory 代码。同步 docs 不改变
冻结代码基线；不得据此直接修改 `dev`。

## 固定工作区与当前施工状态

所有施工单必须先按本节选择工作区；不得因为文件名相同就在另一个 worktree 修改：

```text
WEB_WORKTREE   = D:\project\AI-QA-Assistant
WEB_BRANCH      = web-dev
AGENT_WORKTREE = D:\project\AI-QA-Assistant-agent-memory
AGENT_BRANCH    = agent-dev-infra
```

截至本总控书的当前版本，Web 已完成 `01`、`12a`、`02`、`02a`、`02b`、`03`，以及
`04`、`04a`、`05`、`07`、`08` 的 Web/BFF 侧工作；这些 Web 内容在后续同名单元中
只作审查证据，不得重复实现。Agent 侧已完成 `04`（DTO/开关）、`04a`（私有端点）、
`05`（Resolver）、`06`（Prompt/Recall）、`07`（Planner）、`09-Agent`（受控 Fact
proposal/recall）和 `11-Agent`（开关、安全与无正文可观测性）。`06a` 与 `06b` 是已完成的
基线/迁移前核对单元；`08` 在 `04a` 完成后默认只作审查，不新增 Agent reset 以外的代码。

Web 后续单元和跨工作区验收仍以 `web-dev` 的最新状态为准；不得根据本 Agent 分支重复实施
Web 代码。`09-session-fact-lifecycle.md` 与
`11-security-observability-and-flags.md` 仅为导航页，**不得**作为 `<XX>` 执行；必须使用
带工作区后缀的原子单元。执行者必须先读本节和本单元的“当前状态”；状态为“已完成/审查”的
内容只能审查，不能借执行命令重新施工。

Agent Memory 的冻结**代码**基线固定为：

```text
remote branch: origin/agent-dev-infra
commit: 5955cd0c2a60fe439d4206befb42307a271aef86
subject: feat(agent): complete member B week 1 runtime work
```

允许在 `5955cd0` 之上叠加只修改 `docs/memory-context-plan/**` 的同步提交；在第一笔
Agent Memory 代码提交前，`5955cd0` 必须仍是 HEAD 的祖先，且二者之间不得出现 Runtime
或 Memory 源码差异。唯一已批准的非 docs 例外是经独立 Week-1 回归验证、仅修改
`agent/requirements-week1.txt` 的可复现性修复（提交 `b441acd`）；它不改变 Runtime
行为，也不代表任何 Memory 代码已经迁移。`web-dev@8048e90` 是已完成的 Web 实现和旧 Agent Memory 实现的
迁移来源，不能被 reset、覆盖或整体 merge 到 Agent 开发线。Agent 适配只能选择性迁移
`agent/**` 中的 Memory 文件，并保留 5955 的 lifecycle、共享 Agent 和 ToolExecutor 实现。

## 已冻结的目标

首版提供版本化 `MemorySnapshot`、未覆盖原文 `Tail`、显式确认的 `SESSION MemoryFact` 与确定性 Fact 回忆。首版不提供 Redis、跨会话 `USER` Fact、自动确认 Fact、自动提取敏感信息或风险分级改造。

消息权威源和 Memory 表均在 Web Drizzle/Turso 数据库。Web BFF 是唯一持久化方；Agent 只处理可信 Memory 输入、生成 `ContextArtifact`、确定性回忆和压缩计划。Fact proposal 仅在 `09a-Web` 合同审查后由 `09-Agent` 生成、由 `09-Web` 持久化；`01`--`08` 的 `fact_proposals` 固定为空数组。浏览器不能提交 `userId`、Snapshot、Fact、摘要或压缩版本。

## 关键术语与不变量

| 名称 | 含义 | 必须满足 |
| --- | --- | --- |
| `sequence` | 一个 chat 内单调递增的消息顺序 | 不能用 UUID/时间戳替代；`(chat_id, sequence)` 唯一 |
| `revision` | chat 历史的当前版本 | 编辑/重生成会递增；Snapshot 只对同 revision 有效 |
| Snapshot | 已覆盖历史的版本化摘要检查点 | 每 chat/revision 至多一个 `ACTIVE`；旧版归档 |
| Tail | `sequence > covered_to_sequence` 的原文消息 | 有界；当前输入不能重复出现 |
| Fact | 用户明确确认的会话事实 | 仅 `CONFIRMED` 且未过期的 Fact 可用 |
| `memoryBrief` | Fact + Snapshot 摘要组成的短文本 | 每轮派生，不落库，不替代 RAG 证据 |
| `modelHistory` | memory 系统消息 + Tail | 每轮派生；当前 query 由 Runner 最后追加一次 |

RAG 仍只负责外部知识与 citations；Memory 不能产生或支撑 RAG citation。Trace/日志不得记录 Fact 正文、Snapshot 正文或完整 Prompt。

## 实施顺序

1. `01-web-identity-and-access.md`
2. `12a-web-test-harness.md`
3. `02-message-order-and-lifecycle.md`
4. `02a-sequence-migration-runbook.md`
5. `02b-stream-completion-state-machine.md`
6. `03-memory-schema-and-migration.md`
7. `04-internal-memory-contract.md`
8. `04a-internal-endpoint-specification.md`
9. `05-snapshot-tail-resolution.md`
10. `06a-agent-baseline-lock.md`
11. `06b-agent-infra-5955-reconciliation.md`
12. `06-agent-prompt-and-recall.md`
13. `07-post-turn-compaction.md`
14. `08-history-mutation-and-deletion.md`
15. `09a-fact-idempotency-contract.md`（`09a-Web`）
16. `09-agent-fact-proposal-and-recall.md`（`09-Agent`）
17. `09-web-fact-lifecycle.md`（`09-Web`）
18. `10-fact-web-experience.md`（`10-Web`）
19. `11-agent-flags-security-observability.md`（`11-Agent`）
20. `11-web-flags-security-observability.md`（`11-Web`）
21. `12-test-and-acceptance.md`
22. `13-rollout-and-handoff.md`

`01` 完成后必须先完成 `12a`，使后续所有 Web 单元从第一天就有隔离测试。`02`、`02a` 与 `02b` 必须全部完成，才可建 Memory 表或接入流。`04a` 是唯一服务间接口规范，禁止选择其他返回通道或添加未定义的私有调用；其阶段性端点行为和开关门禁由 04a 自身定义。`06a` 固定 Agent 施工基线，`06b` 完成迁移前适配检查后，`04a`、`05` 与 `06` 才能按各自边界实施；`06` 必须正式以前述四个单元为前置。`07` 先固定敏感值过滤规则，`09a-Web` 先冻结并实现 Fact 去重/幂等合同，`09-Agent` 只能生成受限候选，`09-Web` 才能持久化候选并暴露 Fact API；三者均审查通过后，`10-Web` 才能开始。`11-Agent` 与 `11-Web` 在 `09-Agent` 和 `09-Web` 之后实施；`12` 必须等待 `10-Web`、`11-Agent`、`11-Web` 全部通过。

## 每份施工单必须包含的执行信息

1. 目标、非目标、前置单元与负责人。
2. 当前代码事实与允许修改的绝对路径。
3. 不可破坏的安全/兼容约束。
4. 数据、DTO、HTTP 或事件契约的精确字段与示例。
5. 有序实施步骤；每步的读写边界和失败处理。
6. 单元测试、集成测试、人工核查命令及预期结果。
7. 完成标准、交接输入和明确的停止条件。
8. `施工位置`：明确写出本单元使用的固定工作区、分支，以及哪些跨层内容仅作审查。

## Agent 执行规则

- 不扩展本施工单未列出的功能；特别是不得偷偷引入 Redis、USER Fact、LLM 自动确认或新的队列系统。
- Agent 当前采用单一可写开发线和热点文件写锁。写锁 holder 在交接中记录基线、任务、锁定文件和释放条件；其他成员不得并行修改 `agent.py`、`runtime/runner.py`、`app.py`、`api/chat_routes.py`、`config/settings.py`、`schemas/chat.py`、`orchestration/orchestrator.py`。
- 不修改其他团队文件。跨层契约变更先改共享文档并等待相关 owner Review；Agent Memory 的 Web 文件继续由 `web-dev` 维护。
- 不向公开 `ChatResponse` 添加 Memory 内容；内部字段必须与浏览器输入隔离。
- 助手消息未成功持久化时，禁止确认 Fact 或推进 Snapshot。
- 执行任何 Web migration 前，必须通过 `02a` 验证 Drizzle migration 和运行时使用同一 `TURSO_DATABASE_URL`；禁止依赖两个不同的默认数据库路径。
- Memory 只属于普通 Chat。不得从 `agent/deep_research/**` 导入任何对象、不得让 `/api/chat` 或 Memory 私有端点创建 Research Job，也不得把 Chat `ConversationMemory`、Snapshot、Fact 或 Tail 作为 Deep Research Graph State。
- 任意契约不清、迁移无法回滚、Agent 基线未确定时，停止实现并报告阻塞点。
- 使用“执行 XX”时，执行者仍必须完整阅读本总控、本单元、其前置施工单与当前相关代码；
  只在本单元声明的 `施工位置` 和允许范围内修改。使用“审查 XX”时一律不修改代码或文档。

## 两条公式化工作 Prompt

以下是后续唯一允许复用的执行与审查 Prompt。`<XX>` 必须是本总控列出的**原子单元**，例如
`09-Agent`、`09-Web`、`11-Agent`，不能填写导航页 `09` 或 `11`。这两条 Prompt 不固定
Agent 工作区：执行者必须先从施工单的 `施工位置` 选择唯一可写 worktree。

### 执行 `<XX>`

```text
执行 <XX>。

严格遵守 docs/memory-context-plan/00-execution-guide.md 与本施工单。
完整阅读总控、本施工单、前置施工单和当前相关源码。

先以本施工单“施工位置”为唯一准则选择工作区与分支；不得假设 Agent 工作区。只有 `12` 可以按其
施工单列出的顺序在两个**测试**工作区运行命令；不得借此跨工作区扩大写入范围。
只在本施工单声明的施工位置与允许修改范围内实施；
不开始下一单元，不重复已完成工作，不扩展功能。
严格遵守基线、数据、接口、安全、兼容和停止条件。

完成后运行本施工单规定的测试与检查。

最后按总控交接模板汇报：
单元、基线、改动文件、契约变更、测试结果、未覆盖风险、下一单元是否可开始。
```

### 审查 `<XX>`

```text
审查 <XX>。

完整阅读 docs/memory-context-plan/00-execution-guide.md、本施工单、前置施工单与当前实现。
先以本施工单“施工位置”为唯一准则选择只读工作区；不得假设 Agent 工作区。只有 `12` 可以按其
施工单列出的顺序在两个测试工作区汇总证据。
仅审查，不修改代码或文档。

逐项核对：
1. 是否完整实现目标与每个实施步骤；
2. 是否只修改允许范围内文件；
3. 数据、接口、开关、鉴权、失败处理是否符合施工单；
4. 是否触犯禁止项、破坏公开兼容性或冻结 Runtime；
5. 测试是否实际运行并满足验收；
6. 是否满足进入下一单元条件。

最后只输出：
- PASS 或 FAIL；
- 证据：文件路径、行号、测试命令与结果；
- 若 FAIL：按优先级列出必须修复项；
- 下一单元是否允许开始。
```

`12` 仍必须在两个工作区分别运行规定测试并汇总证据；`13` 的执行 Prompt 只可完成发布就绪审查、
文档和本地回滚演练。任何真实环境开关、灰度、推送、部署或回滚都需要用户另行明确授权。

## 建议的交接模板

```text
单元：XX
基线：<commit>
改动文件：<absolute paths>
契约变更：<none 或链接>
测试：<命令与结果>
未覆盖风险：<具体风险>
下一单元可开始：是/否；原因
```
