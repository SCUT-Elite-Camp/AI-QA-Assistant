# 02a sequence/revision 迁移与数据库地址 Runbook

## 目标

将既有 chat/message 安全迁移到 `history_revision + sequence` 模型，并消除当前 Drizzle migration 配置与运行时 `useDrizzle()` 默认数据库路径不一致的风险。此单元是必须执行的迁移 runbook，不允许 Agent 自行选择数据库或回填方法。

前置：`02`。负责人：Web。后续：`03`。

## 唯一数据库规则

所有 migration、开发服务、测试和 BFF 运行必须显式使用相同的 `TURSO_DATABASE_URL`。首选本地值：

```text
TURSO_DATABASE_URL=file:.data/sqlite.db
```

将 `web/server/utils/drizzle.ts` 的 fallback 改为与 `web/drizzle.config.ts` 同一位置；新建/更新 `web/.env.example` 给出上述无密钥示例。非开发环境缺少 `TURSO_DATABASE_URL` 时必须启动失败，不能回退到文件路径。

已有本机历史若位于 `D:\project\AI-QA-Assistant\data-persistence\data\sqlite.db`，只允许通过显式设置 `TURSO_DATABASE_URL=file:../data-persistence/data/sqlite.db` 执行一次迁移；迁移和运行必须在同一显式 URL 下完成。禁止一个命令使用 `.data`、另一个命令使用旧路径。

## 精确迁移步骤

1. 记录迁移目标 URL，停止写入该数据库的 Web 服务，并复制该 SQLite 文件或执行 Turso 受控备份。没有可恢复备份不得继续。
2. 先按 `02` 修改 schema：`chats.history_revision DEFAULT 1`、`chats.next_message_sequence DEFAULT 1`、`messages.sequence`、`messages.history_revision DEFAULT 1`、`messages.request_id nullable` 和唯一索引声明。
3. 在 `web` 执行 `pnpm run db:generate`。只允许修改这次生成的 SQL migration 文件；绝不编辑 `migrations/meta`。
4. 在生成 SQL 的 messages 表重建/复制阶段，使用下列确定性表达式写入历史值：

```sql
ROW_NUMBER() OVER (
  PARTITION BY chat_id
  ORDER BY created_at ASC, id ASC
) AS sequence,
1 AS history_revision,
NULL AS request_id
```

若生成的 SQL 不是重建表而是 ADD COLUMN，先添加 nullable fields，执行同一 `ROW_NUMBER()` 回填，再以 SQLite 表重建方式加 `NOT NULL` 与唯一索引。不得给所有旧消息填同一个默认 sequence。

5. 在所有 messages 回填后更新每个 chat：

```sql
UPDATE chats
SET history_revision = 1,
    next_message_sequence = COALESCE(
      (SELECT MAX(sequence) + 1 FROM messages WHERE messages.chat_id = chats.id),
      1
    );
```

6. 创建 `UNIQUE(chat_id, sequence)` 与 request-id 唯一索引，运行 migration。迁移失败时恢复备份或使用经 Review 的 forward fix；不得手工删除业务表。
7. 执行校验 SQL：每个 chat 的 sequence 从 1 连续递增、无 null/重复；`next_message_sequence = max(sequence)+1`；所有旧消息 revision=1。

## 修改范围与测试

- `web/drizzle.config.ts`
- `web/server/utils/drizzle.ts`
- `web/.env.example`
- `web/server/database/schema.ts`
- 本次新 SQL migration；对应 Vitest migration fixture。

先在历史数据 fixture 副本运行，再在目标数据库运行。运行：`pnpm test -- sequence-migration`、`pnpm run db:migrate`、`pnpm run typecheck`、`pnpm run lint`。若 SQLite/libSQL 不支持 `ROW_NUMBER()`，停止并报告版本与错误；不得改用不稳定排序。

## 完成标准

migration URL 与 runtime URL 完全相同；旧数据可读、无 sequence 冲突；新写入从正确的 next sequence 开始。交接 migration ID、目标 URL（脱敏）和校验结果给 `03`。
