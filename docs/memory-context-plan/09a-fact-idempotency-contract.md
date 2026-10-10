# 09a-Web Fact 去重、幂等与 HTTP 合同

## 目标与当前状态

在任何 Fact 路由、UI 或 Agent proposal 生成之前，冻结并实现 Web 权威 Repository 的去重、
确认、撤销与过期规则。本单元的唯一可写方是 Web；Agent 只审查共享 DTO，**不得**修改
Agent 源码。

`03` 已提供 `memoryFacts` 表、`createFactProposal()`、`confirmFact()` 与 `revokeFact()` 的
基础实现，但它们还不是本单元的验收结论：本单元必须将其收敛到下述固定合同。`09-Agent` 才
生成候选，`09-Web` 才创建浏览器 Fact routes 和消费 Agent 返回的候选，`10-Web` 才实现 UI。

前置：`03`、`04`、`07`、`08` 均已审查通过。后续：`09-Agent`、`09-Web`、`10-Web`、`12`。
负责人：Web；Agent owner 只做契约审查。

## 施工位置与允许修改范围

```text
唯一工作区：D:\project\AI-QA-Assistant
唯一分支：web-dev
```

允许修改：

- `web/server/utils/memoryRepository.ts`
- `web/server/utils/memoryContract.ts`
- `web/tests/utils/memoryRepository.test.ts`
- `web/tests/utils/memoryContract.test.ts`
- 新建仅用于本单元的 `web/tests/utils/factIdempotency.test.ts`
- `docs/memory-context-plan/**` 中本单元的更正说明

禁止修改：任何 `agent/**`、任何浏览器 route/UI、`web/server/routes/**`、数据库 schema/migration、
公开 ChatResponse、Snapshot/Tail/compaction 实现。若发现实现本合同需要 schema migration，停止并报告；
不得在 09a 临时扩表。

## 输入、输出与固定兼容策略

### Agent 内部候选兼容 envelope

`04` 已冻结的内部 `FactProposal` 兼容 envelope 保持如下四字段：

```json
{
  "category": "GOAL | PREFERENCE | PLAN_CONSTRAINT",
  "value": "candidate text",
  "source_message_id": "persisted-user-message-id",
  "expires_at": null
}
```

`expires_at` 是既有内部 schema 的必填可空兼容字段，不能在本单元删除。`09-Agent` 必须始终输出
`null`；`09-Web` 对任何 Agent 提供的非 null 值一律忽略，绝不把它写入数据库或返回浏览器。
浏览器永远不能提交 `value`、`expires_at`、`user_id`、`chat_id`、`history_revision`、`scope` 或
`proposal_key`。

Repository 对外使用 `MemoryFactDto`；后续浏览器 route 必须只序列化
`id/category/status/value/sourceMessageId/expiresAt/confirmedAt/createdAt`，日期为 UTC ISO-8601 字符串，
不得暴露 user/chat/revision/proposal key。该浏览器 JSON 约定在本单元冻结、由 `09-Web` 实现。

### Proposal 去重

proposal key 是 UTF-8 文本以下字段以 NUL 分隔后计算 SHA-256 小写十六进制：

```text
chat_id \0 history_revision \0 source_message_id \0 category \0 normalized_value
```

`normalized_value` 只做 Unicode NFC、trim 与连续空白折叠为一个空格；不改写大小写、中文或标点。
Web 是唯一计算 key 的一方。每个事务都必须先验证 actor 拥有 chat、source message 属于同一 chat/
revision；真正的 proposal 创建还必须由 `09-Web` 验证 source 的 role 为 `user`。

冲突处理固定如下：新行返回 `{ created: true, fact }`；同 key 的 `PROPOSED`、`CONFIRMED` 或
`REVOKED` 都返回 `{ created: false, fact: existing }`，HTTP 分别为 201 与 200。REVOKED 不得无声
复活；用户必须以新的 source message 提出新候选。

### 确认、撤销与服务端过期时间

| 请求 | 当前状态 | 新状态 | HTTP | 固定副作用 |
| --- | --- | --- | --- | --- |
| proposal | 无 | PROPOSED | 201 | 写 proposal key；`expires_at=null` |
| proposal | 任意同 key | 不变 | 200 | 返回既有行 |
| confirm | PROPOSED | CONFIRMED | 200 | 首次写 confirmed_at 与 expires_at |
| confirm | CONFIRMED | 不变 | 200 | 不改任何时间戳 |
| confirm | REVOKED | 不变 | 409 | `fact_revoked` |
| revoke | PROPOSED/CONFIRMED | REVOKED | 200 | 首次写 revoked_at |
| revoke | REVOKED | 不变 | 200 | 不改任何时间戳 |

`confirmFact()` 的公开输入不得再接受 `expiresAt`。Repository 在首次状态迁移时用其内部 `now`
（测试可注入）按 Fact category 计算：`PLAN_CONSTRAINT = now + 30 days`；`GOAL/PREFERENCE = now +
90 days`。revoke 不清空 value/source/confirmedAt/expiresAt。解析 Context 时只可读取同 revision、
`CONFIRMED` 且未过期 Fact；本单元不得把 `getVisibleFacts()` 放宽为返回 PROPOSED。

### 后续浏览器 HTTP 合同（只冻结、不在本单元建 route）

`09-Web` 必须实现以下合同；其所有错误 body 一律为 `{ "code": "...", "message": "..." }`，
不得回显 Fact value 或 source 正文：

| 方法 | 请求 body | 成功响应 | 失败 |
| --- | --- | --- | --- |
| `POST /api/chats/:id/memory/facts/proposals` | `{ source_message_id, category }` | 201/200 `{ created, fact }` | 404 chat/source/fact 不可见；422 `fact_source_not_user_message` 或 `fact_sensitive`；409 `session_fact_disabled` |
| `GET /api/chats/:id/memory/facts` | 无 | 200 `{ facts: FactView[] }` | 404 不属于 actor；409 `session_fact_disabled` |
| `POST /api/chats/:id/memory/facts/:factId/confirm` | 无 | 200 `{ fact }` | 404；409 `fact_revoked` 或 `session_fact_disabled` |
| `POST /api/chats/:id/memory/facts/:factId/revoke` | 无 | 200 `{ fact }` | 404；409 `session_fact_disabled` |

`09-Agent` 与 `09-Web` 必须先各自引入默认 false 的 `SESSION_FACT_ENABLED` gate，使尚未发布的 Fact
功能 fail closed；`11-Agent` 与 `11-Web` 只集中校验、扩展降级/观测并保留该精确语义。09-Web 的 gate
关闭时返回 `session_fact_disabled`，测试可注入 true；不得自行引入任何 Redis 或其他开关。

## 有序实施步骤

1. 审查当前 Repository 与上述合同的差异，保留既有 Snapshot/Tail API 的行为。
2. 固定并测试 proposal key/normalization、冲突读取、actor/chat/revision/source 所有权约束。
3. 将 confirm 的过期计算收回 Repository：移除可由调用方控制的 expiresAt，保证并发 confirm/revoke
   只写入一次时间戳，并返回稳定的幂等结果。
4. 在 `memoryContract.ts` 保留四字段内部 proposal envelope，并以测试证明 `expires_at` 可为 null；
   不把该字段加入公开 ChatResponse。
5. 在测试中使用固定 `now`，覆盖 30/90 天边界、已过期 Fact 不可见、REVOKED 不可重新 confirm、
   同 key REVOKED 不可重建、两次并发 proposal 只产生一行、跨用户 Fact ID 返回 404。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant\web
pnpm exec vitest run tests/utils/memoryRepository.test.ts tests/utils/memoryContract.test.ts tests/utils/factIdempotency.test.ts
pnpm run typecheck
pnpm run lint
```

完成条件：上述命令成功；Repository contract 的每个状态表分支均有回归；diff 只含允许范围。

停止并报告：共享 Agent/Web schema 对 `expires_at` 的 nullable 语义不一致；需要 migration；无法在
transaction 内读取冲突行；或任何实现要求浏览器提交权威字段。交接给 `09-Agent` 的内容是四字段
内部 envelope 和 null/ignore 规则；交接给 `09-Web` 的内容是完整 HTTP 合同、错误码与 Repository
幂等语义。
