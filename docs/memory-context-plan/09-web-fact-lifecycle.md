# 09-Web Fact 持久化、手动保存与受限 API

## 目标与当前状态

Web BFF 是唯一 Fact writer。本单元消费 `09-Agent` 的内部候选，在助手消息成功持久化后创建
`PROPOSED` Fact；同时提供用户手动从当前 revision 的 user message 创建候选、读取、确认和撤销 API。
它不实现 UI（属于 `10-Web`），不改变 Agent policy。

前置：`09a-Web` 与 `09-Agent` 均审查通过，`02b` 的 assistant persistence 状态机可用。后续：
`10-Web`、`11-Web`、`12`。负责人：Web。

## 施工位置与允许修改范围

```text
唯一工作区：D:\project\AI-QA-Assistant
唯一分支：web-dev
```

允许修改：

- `web/server/routes/api/chats/[id].post.ts`
- 新建 `web/server/utils/sessionFactGate.ts`（只解析 `SESSION_FACT_ENABLED`，默认 false）
- 新建 `web/server/routes/api/chats/[id]/memory/facts.get.ts`
- 新建 `web/server/routes/api/chats/[id]/memory/facts/proposals.post.ts`
- 新建 `web/server/routes/api/chats/[id]/memory/facts/[factId]/confirm.post.ts`
- 新建 `web/server/routes/api/chats/[id]/memory/facts/[factId]/revoke.post.ts`
- `web/server/utils/memoryRepository.ts` 与仅为 route DTO 增加的 helper
- 新建 `web/server/utils/sensitiveMemoryValue.ts`
- `web/server/utils/memoryContract.ts`
- `web/.env.example`（只增加 `SESSION_FACT_ENABLED=false` 占位）
- 对应 `web/tests/utils/**`、`web/tests/routes/**`、`web/tests/integration/**`

禁止修改浏览器组件/composable、Agent 文件、数据库 schema/migration、公开 ChatResponse、Snapshot/Tail
Resolver、compaction 规则或 Deep Research。Route 只能使用 `requireOwnedChat` 和服务器身份，不能接收
浏览器 user/chat/revision/value/expiry/scope/proposal key。

## 固定输入、输出与持久化时序

### Agent 候选消费

只有 authenticated actor、persistent Memory 已启用且成功走 private `/api/internal/chat` 时，BFF 才读取
`memory_decision.fact_proposals`。它必须先完成 `02b` 的助手消息持久化；仅在 `ASSISTANT_PERSISTED`
之后，逐条验证：source ID 等于本轮已持久化 user message、source role 为 user、chat/revision/actor 一致、
category 合法、value 非敏感。验证通过才调用 09a Repository proposal upsert。助手持久化失败、SSE 失败/取消、
private 调用回退公开 chat、Agent 返回无效 DTO 或 proposal 创建失败时，不创建 Fact，也不改变聊天成功响应。

`expires_at` 永远由 09a Repository 在 confirm 时计算；BFF 忽略 Agent envelope 中的该值。proposal 失败只记录
不含正文的安全事件，当前聊天仍成功。

### 手动 proposal 与 Fact routes

四条 route 严格实现 09a 的 HTTP 合同。`sessionFactGate` 默认 false；只有测试或经环境显式打开时才
允许读写 Fact，关闭时在 ownership 校验后固定返回 409 `session_fact_disabled`。11-Web 必须复用该 gate
并集中纳入完整配置校验，不得改变默认值。手动 proposal body 只能是：

```json
{ "source_message_id": "...", "category": "GOAL | PREFERENCE | PLAN_CONSTRAINT" }
```

服务器读取 source message 的文本 part，拒绝不存在、非 user、非当前 revision、空文本、敏感内容或非 owner；
从文本生成 value，计算 key。`GET` 固定返回当前 revision 的 `PROPOSED` 与 `CONFIRMED`、未过期 Fact，
按 `createdAt ASC, id ASC`；不接受 status/revision query 参数，绝不返回 REVOKED/旧 revision/其他用户数据。
`getVisibleFacts()` 的 Confirmed-only 语义不能被改变；为 GET 新增独立 Repository reader。

confirm/revoke 只接受 path 的 Fact ID，无 body。所有 route 使用 09a 的稳定 code；404 不区分无 chat、无 Fact
或非 owner。HTTP response 只能含 09a `FactView`，不回显敏感 source 正文或内部 key。

### TypeScript 敏感值 helper

`sensitiveMemoryValue.ts` 必须是无副作用、无日志的纯函数，逐项复现 `07` 的规则：不区分大小写的
`password|passwd|secret|token|api key|private key|access key`、18 位身份证、去非数字后长度 13--19、
以及 `银行卡|银行账户|账号|住址|详细地址|诊断|病历|疾病|药物|金融账户`。同一表驱动样例必须在
Python 与 TypeScript 两侧通过；不得跨语言 import，也不得扩展词表。

## 有序实施步骤

1. 新建 `sessionFactGate.ts` 与 `web/.env.example` 的默认 false 配置，并测试默认关闭、显式打开和非 boolean
   环境值 fail closed；不得由浏览器传开关。
2. 先实现/测试 TypeScript 敏感 helper，并与 `agent/tests/unit/test_sensitive_value.py` 的同名样例逐项对齐。
3. 基于 09a Repository 增加 current-revision Fact reader 与 source user-message reader；不修改 Confirmed-only
   Resolver reader。
4. 实现四条 route、所有权与 error mapping；手动 proposal 只使用服务器读取的 source 文本。
5. 在 `[id].post.ts` 的助手持久化成功分支接入 Agent proposal 消费；任何 Fact 失败均吞掉为安全的
   非阻断分支，绝不让浏览器收到 `memory_decision`。
6. 为 Agent proposal、手动 proposal、双击 confirm/revoke、过期、REVOKED、编辑后 revision 变化、
   cross-user、敏感值和 SSE 失败分别补测试。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant\web
pnpm exec vitest run tests/utils/memoryRepository.test.ts tests/utils/factIdempotency.test.ts tests/routes/factLifecycle.test.ts tests/integration/chat-memory-flow.test.ts
pnpm run typecheck
pnpm run lint
```

完成条件：全部命令成功；自动候选只在助手成功持久化后产生；手动/API 路径均无法跨用户、跨 revision
或保存敏感文本；公开 ChatResponse 不含 MemoryDecision；不创建 Deep Research Job。

停止并报告：09a/09-Agent contract 未通过；需要浏览器传权威字段；需要 schema migration；现有 SSE 成功点
不明确；或 TypeScript 敏感样例不能与 07 对齐。交接给 `10-Web` 的内容是稳定 FactView/错误码、四条 route
与可复现测试 fixture；交接给 `11-Web` 的内容是所有需要 feature gate 的调用点。
