# Persistent Memory 施工总控书

## 使用方式

本目录是一组可直接执行的施工单。任何 Agent 必须先读本文件，再严格按编号完成单元；一次只实施一个单元。完成一个单元后必须运行该文档列出的测试、检查工作区只包含允许的文件，并在 PR/交接信息中报告验收结果。没有通过验收不得开始下一单元。

本目录当前被 `.gitignore` 忽略，是团队确认前的本地施工蓝图；不能据此直接修改 `dev`。实现分别进入 `web-dev` 与 `agent-dev`，通过 PR 合入。

## 已冻结的目标

首版提供版本化 `MemorySnapshot`、未覆盖原文 `Tail`、显式确认的 `SESSION MemoryFact` 与确定性 Fact 回忆。首版不提供 Redis、跨会话 `USER` Fact、自动确认 Fact、自动提取敏感信息或风险分级改造。

消息权威源和 Memory 表均在 Web Drizzle/Turso 数据库。Web BFF 是唯一持久化方；Agent 只处理可信 Memory 输入、生成 `ContextArtifact`、Fact 提议、确定性回忆和压缩计划。浏览器不能提交 `userId`、Snapshot、Fact、摘要或压缩版本。

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
11. `06-agent-prompt-and-recall.md`
12. `07-post-turn-compaction.md`
13. `08-history-mutation-and-deletion.md`
14. `09-session-fact-lifecycle.md`
15. `09a-fact-idempotency-contract.md`
16. `10-fact-web-experience.md`
17. `11-security-observability-and-flags.md`
18. `12-test-and-acceptance.md`
19. `13-rollout-and-handoff.md`

`01` 完成后必须先完成 `12a`，使后续所有 Web 单元从第一天就有隔离测试。`02`、`02a` 与 `02b` 必须全部完成，才可建 Memory 表或接入流。`04a` 是唯一服务间接口规范，禁止选择其他返回通道或添加未定义的私有调用。`06a` 固定 Agent 施工基线，`06` 只能在该基线之上实施。`09` 与 `09a` 一起完成后，`10` 才能开始。

## 每份施工单必须包含的执行信息

1. 目标、非目标、前置单元与负责人。
2. 当前代码事实与允许修改的绝对路径。
3. 不可破坏的安全/兼容约束。
4. 数据、DTO、HTTP 或事件契约的精确字段与示例。
5. 有序实施步骤；每步的读写边界和失败处理。
6. 单元测试、集成测试、人工核查命令及预期结果。
7. 完成标准、交接输入和明确的停止条件。

## Agent 执行规则

- 不扩展本施工单未列出的功能；特别是不得偷偷引入 Redis、USER Fact、LLM 自动确认或新的队列系统。
- 不修改其他团队文件。跨层契约变更先改共享文档并等待相关 owner Review。
- 不向公开 `ChatResponse` 添加 Memory 内容；内部字段必须与浏览器输入隔离。
- 助手消息未成功持久化时，禁止确认 Fact 或推进 Snapshot。
- 执行任何 Web migration 前，必须通过 `02a` 验证 Drizzle migration 和运行时使用同一 `TURSO_DATABASE_URL`；禁止依赖两个不同的默认数据库路径。
- 任意契约不清、迁移无法回滚、Agent 基线未确定时，停止实现并报告阻塞点。

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
