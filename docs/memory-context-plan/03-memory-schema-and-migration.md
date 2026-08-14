# 03 Snapshot 与 SESSION Fact 数据模型

## 目标

在 Web 的权威数据库中创建可迁移、可删除、可并发控制的 Snapshot 与 Fact 表。此单元只做数据结构、约束和仓储 helper，不做 Prompt、UI 或 Agent 行为。

前置：`01`、`02`。负责人：Web（需 Data Persistence reviewer）。后续依赖：`04`、`05`、`07`、`09`。

## 表定义

`memory_snapshots`：

```text
id text PK
user_id text NOT NULL -> users.id
chat_id text NOT NULL -> chats.id ON DELETE CASCADE
history_revision integer NOT NULL
version integer NOT NULL
covered_from_sequence integer NOT NULL
covered_to_sequence integer NOT NULL
covered_from_message_id text NOT NULL
covered_to_message_id text NOT NULL
summary text NOT NULL
status text NOT NULL: ACTIVE | ARCHIVED
created_at integer NOT NULL
archived_at integer NULL
UNIQUE(chat_id, history_revision, version)
INDEX(chat_id, history_revision, status, covered_to_sequence)
```

`memory_facts`：

```text
id text PK
user_id text NOT NULL -> users.id
chat_id text NOT NULL -> chats.id ON DELETE CASCADE
history_revision integer NOT NULL
source_message_id text NULL -> messages.id ON DELETE SET NULL
category text NOT NULL: GOAL | PREFERENCE | PLAN_CONSTRAINT
scope text NOT NULL: SESSION
status text NOT NULL: PROPOSED | CONFIRMED | REVOKED
value text NOT NULL
proposal_key text NOT NULL
expires_at integer NULL
confirmed_at integer NULL
revoked_at integer NULL
created_at integer NOT NULL
INDEX(user_id, chat_id, history_revision, status, expires_at)
UNIQUE(chat_id, history_revision, proposal_key)
```

首版不建 USER scope；若以后扩展，必须新开施工单和迁移，不能在 API 中偷偷放开枚举。

## 实施步骤

1. 在 `web/server/database/schema.ts` 定义表、relations、枚举约束和索引；所有外键都指向 Web 权威表。
2. 用 `pnpm run db:generate` 生成 migration。禁止手写 journal/snapshot 元文件。messages/chats 的回填顺序和统一数据库地址必须严格执行 `02a`。
3. 审阅生成 SQL：现有 chat/messages 必须零数据丢失；新增非空字段须有默认值或安全回填；确认 Turso/SQLite 支持的 partial-index 语法后才使用。若不支持“仅一个 ACTIVE”的 partial unique index，由 `07` 使用事务 + 乐观更新保证。
4. 新建 `web/server/utils/memoryRepository.ts`，只暴露显式方法：读取 active snapshot、按 sequence 读取 Tail、读取可见 Fact、创建 proposal、确认/撤销 Fact、归档/写入 Snapshot、按 chat 删除。方法都接收 `actorUserId` 并再次约束 user/chat。Fact 的 `proposal_key` 算法和所有状态请求的幂等结果严格执行 `09a`。
5. Snapshot/Facts 的正文不写入通用日志；Repository 返回 DTO，不返回任意 SQL 行对象。

## 必测场景

- 删除 chat 后 Snapshot 和 SESSION Fact 被级联删除。
- 同 chat 同 revision 的 Snapshot version 不可重复。
- 无法把 A 的 Fact 绑定到 B 的 chat。
- source message 删除后 Fact 不会悬挂无效外键。

## 完成条件

迁移可在空库和已有本地库执行；schema/typecheck 成功；Repository API 具备单元测试。交接 Repository 的读写 DTO 给 `04`，不得让 Agent 直接查询数据库。
