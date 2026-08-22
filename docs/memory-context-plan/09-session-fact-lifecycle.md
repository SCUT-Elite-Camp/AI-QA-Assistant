# 09 SESSION Fact 提议、确认、撤销与回忆后端

## 目标

实现受用户控制的会话事实。Fact 是独立于 Snapshot 的结构化状态：只在确认后可作为 `memoryBrief` 或显式回忆的依据。

前置：`03`、`04`、`06`、`07`、`08`。负责人：Agent + Web。后续依赖：`10`、`12`。

## 生命周期与业务规则

```text
明确记忆请求 / 手动选择用户消息 -> PROPOSED
用户确认 -> CONFIRMED
用户拒绝或撤销 -> REVOKED
到期 / chat 删除 / revision 变更 -> 不可见
```

首版只允许三类：`GOAL`、`PREFERENCE`、`PLAN_CONSTRAINT`，scope 固定 `SESSION`。默认有效期：Plan Constraint 30 天；Goal/Preference 90 天。过期记录可保留审计状态，但 resolve 必须忽略。

## 提议规则

- Agent 只对用户的明确记忆意图提出候选，如“请记住我的目标是…”。
- 普通聊天、模型回答、检索内容、工具输出绝不生成 Fact proposal。
- 提议返回 category、规范化 value、source message ID；不直接写 CONFIRMED。Web Repository 按类别固定计算到期时间，忽略 Agent 提供的任何 `expires_at`：`PLAN_CONSTRAINT=30天`，`GOAL/PREFERENCE=90天`。
- 复用 `07` 已冻结的 `isSensitiveMemoryValue(text)` 规则。Agent 的纯 helper 已在 `07` 创建；
  Web 需要以 TypeScript 实现相同语义，不能跨语言直接 import Python，也不得自行增删匹配规则。
  必须与 `07` 的表驱动命中/非命中样例一致；命中时拒绝保存/摘要，且不记录原文到日志。
- Web 还必须支持用户手动从一条 user message 发起 proposal；服务器重新验证 message 属于 actor/chat/revision。

## 内部接口

所有路由先 `requireOwnedChat`：

```text
POST   /api/chats/:id/memory/facts/proposals
GET    /api/chats/:id/memory/facts
POST   /api/chats/:id/memory/facts/:factId/confirm
POST   /api/chats/:id/memory/facts/:factId/revoke
```

`GET /api/chats/:id/memory/facts` 不接受浏览器的 status/revision 参数；服务器固定返回当前 chat、当前 `history_revision`、当前 actor 可见且未过期的 `PROPOSED` 与 `CONFIRMED` Fact，按 `created_at ASC, id ASC` 排序，且从不返回 `REVOKED`、旧 revision 或其他用户 Fact。该 GET 是 Fact UI 的唯一读取来源。

confirm/revoke 的状态机、proposal 去重键和 HTTP 响应已由 `09a` 固定。confirm 仅接受 Fact ID，不接受浏览器改写的 user/chat/value/scope；Repository 用 actor/chat/fact/status 条件读取和更新。

## 验收

- PROPOSED/REVOKED/过期/旧 revision Fact 不进入 ContextArtifact。
- A 无法确认、撤销、读取 B 的 Fact。
- 用户确认后，明确回忆问题可不调用模型地返回正确 Fact；无 Fact 返回确定性空结果。
- 任何模型输出和敏感输入均不会产生 Confirmed Fact。

## 交接

将稳定 API 与前端 DTO 交给 `10`；将 Fact 计数和不含正文的审计事件交给 `11`。
