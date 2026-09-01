# 02 消息顺序、revision 与回合生命周期

## 目标

为 Snapshot/Tail 提供可靠的覆盖边界，并定义重试、失败、取消和消息落库的唯一时序。UUID 与 `createdAt` 都不能替代 chat 内顺序。

前置：`01`。负责人：Web。后续依赖：`03`、`05`、`07`、`08`。

## 目标数据契约

在 `chats` 增加：

```text
history_revision: integer NOT NULL DEFAULT 1
next_message_sequence: integer NOT NULL DEFAULT 1
```

在 `messages` 增加：

```text
sequence: integer NOT NULL
history_revision: integer NOT NULL
request_id: text NULL
```

约束：`UNIQUE(chat_id, sequence)`；若 `request_id` 不为 null，则 `UNIQUE(chat_id, request_id, role)`。新 chat 从 revision=1、sequence=1 开始。消息排序始终使用 `sequence ASC`。

## 允许修改范围

- `D:\project\AI-QA-Assistant\web\server\database\schema.ts`
- 新 Drizzle migration 与 `migrations/meta/*`（先由 `pnpm run db:generate` 生成；SQL 回填补丁仅按 `02a` 执行，禁止手改 meta）
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id].post.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\messages\[id].delete.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats.post.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\save-standalone.post.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id]\branch.post.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id].get.ts`
- 新建 `D:\project\AI-QA-Assistant\web\server\utils\messageLifecycle.ts` 及测试。

## 实施步骤

1. 使用 `messageLifecycle.ts` 的单一 `appendMessage()`。在事务中以 `UPDATE chats SET next_message_sequence = next_message_sequence + 1 ... RETURNING next_message_sequence - 1 AS sequence` 获取 sequence，再插入消息；不得用“查询最大 sequence + 1”。若 libSQL/Turso 不支持此语句，停止实施并回报，不得退回时间戳排序或自行发明替代算法。
2. 将用户最后一条消息的 UI message ID 作为 `request_id`。同一 `request_id` 重试必须返回既有记录，不重复分配 sequence。
3. 用户消息必须在调用 Agent 前持久化；取得 `messageId`、`sequence` 与 `history_revision` 后构造内部 Agent 输入。
4. 助手消息的 ID、成功条件、`onFinish` 行为与失败处理严格按 `02b` 执行；错误文字、取消流和半截流不伪装成成功助手消息。
5. 无成功助手配对的用户消息可存在于 Tail，但 `07` 压缩时必须排除不完整的最后回合。
6. 将现有编辑/重生成的 `createdAt, id` 排序改为 `sequence` 排序。

## 禁止项

- 不得让 Agent 再写一份用户/助手消息到自己的 SQLite 审计表作为 Memory 权威源。
- 不得在浏览器断开后把已缓冲的半截答案写成正式助手消息。
- 不得把 `Date.now()` 作为请求幂等键。

## 验收

- 并发两次发送与同一请求重试不会得到重复 sequence 或重复用户消息。
- 同毫秒创建的多条消息仍严格按 sequence 排序。
- Agent 错误/取消时用户消息保留，助手消息和 Snapshot 均不前进。
- `pnpm run db:generate`、`pnpm run db:migrate`、`pnpm run typecheck`、`pnpm run lint` 成功。

## 交接

将 `(chatId, actorUserId, currentMessageId, currentSequence, historyRevision)` 交给 `04`；将完结助手消息 ID/sequence 交给 `07`。
