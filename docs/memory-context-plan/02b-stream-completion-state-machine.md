# 02b 流式回答完成与助手消息持久化状态机

## 目标

锁定现有模拟 SSE 流的助手消息 ID、成功条件和落库方式，避免依赖 AI SDK `onFinish(messages)` 是否自动包含 writer 写入的助手消息。此单元让后续 Snapshot 只能基于真实成功回合推进。

前置：`02`。负责人：Web。后续：`07`。

## 固定状态机

```text
USER_PERSISTED
  -> AGENT_SUCCEEDED (status=success | clarification_required)
  -> STREAMING
  -> STREAM_COMPLETED
  -> ASSISTANT_PERSISTED
  -> COMPACTION_ELIGIBLE

任意 Agent error / abort / writer error / onFinish DB error
  -> NO_ASSISTANT_PERSISTENCE
  -> NO_COMPACTION
```

## 精确实现规则

1. 用户消息已由 `appendMessage()` 写入并取得 sequence 后才允许请求 Agent。
2. Agent 私有响应为 success 或 clarification_required 时，BFF 立刻生成一次 `assistantMessageId = crypto.randomUUID()`，并将该 ID 作为 `text-start/text-delta/text-end` 的固定 writer ID；不能使用 `Date.now()`。
3. 在 route closure 中累计 `assistantContent`、`streamCompleted=false`、`agentSucceeded=true`。只在 `text-end` 成功写入后设 `streamCompleted=true`。
4. `event.runtime.node.req` 的 `close` 处理必须设置 `clientAborted=true` 并 abort；捕获 writer/Agent 异常必须设置 `streamFailed=true`。
5. `onFinish` 不读取或持久化其 `messages` 参数。仅当 `agentSucceeded && streamCompleted && !clientAborted && !streamFailed && assistantContent.trim()` 时，调用 `appendMessage()` 写一条 role=assistant 的消息，并带当前 revision 与新 sequence。
6. 助手落库失败：记录脱敏错误，不调用 compaction，也不将失败消息重试为新 sequence；用户刷新后看不到该助手消息。重试必须从用户发起的新请求开始。
7. clarification 的持久正文为 `agentData.answer || agentData.message`；错误 UI 文本不得持久化为 assistant。
8. 只有 `ASSISTANT_PERSISTED` 后才调用 `04a` 的 compaction-plan endpoint；其失败不影响已保存助手消息。

## 允许修改范围

- `web/server/routes/api/chats/[id].post.ts`
- `web/server/utils/messageLifecycle.ts`
- Vitest route/lifecycle tests。

## 验收

- 任意成功回合仅有一条助手消息，ID 与 sequence 可预测且不重复。
- 浏览器中断、Agent 4xx/5xx、writer error、DB insert error 都不会写助手消息或 Snapshot。
- `onFinish` 的 messages 参数即使为空、包含重复 user 或包含未知 tool message，结果仍正确。
- success 与 clarification 都可持久；当前前端可正常展示后刷新。

## 交接

向 `07` 提供明确的 `assistantMessageId/sequence/revision`，并报告状态机负向测试结果。
