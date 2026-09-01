# 12a Web 测试基座与临时数据库规范

## 目标

为 Web Memory 单元固定可重复的测试框架、临时数据库和命令。没有测试基座，其他施工单不得声称 migration、所有权或流式状态机已经验收。

前置：`01`。负责人：Web。后续：`02`、`02a`、`02b`、`03`、`12`。

## 固定技术选择

- 测试框架：Vitest，加入 `web` 的 devDependencies。
- 脚本：`"test": "vitest run"`，`"test:watch": "vitest"`。
- 配置：新建 `web/vitest.config.ts`；测试文件为 `web/tests/**/*.test.ts`。
- 数据库：每个 suite 使用唯一临时文件 `file:<temp>/memory-test.db`，绝不使用开发 `.data/sqlite.db` 或 Turso 生产 URL。
- 迁移：测试 global setup 用 `drizzle-orm/libsql/migrator` 对该临时 URL 执行 `web/server/database/migrations`；测试结束删除临时目录。

## 必须修改的可测试性边界

1. `web/server/utils/drizzle.ts` 导出仅测试使用的 `resetDrizzleForTests()`，它清空模块级 `_db`。生产代码不得调用。
2. 删除或隔离 `useDrizzle()` 内部临时 `CREATE TABLE/ALTER TABLE` 自修复 SQL；schema 只能由 Drizzle migration 建立。保留它会使迁移测试掩盖真实问题。
3. 测试在设定 `TURSO_DATABASE_URL` 后再 import database module，调用 reset，避免连接复用到其他 suite。
4. 路由测试若无法直接构造 Nitro event，先抽取可测试的 `chatAccess`、`messageLifecycle`、`memoryRepository`、`agentInternalClient` 纯服务函数；少量 route 仅做 HTTP 集成测试。

## 初始测试文件

```text
web/tests/migrations/sequence-migration.test.ts
web/tests/utils/chatAccess.test.ts
web/tests/utils/messageLifecycle.test.ts
web/tests/utils/memoryRepository.test.ts
web/tests/utils/agentInternalClient.test.ts
web/tests/integration/chat-memory-flow.test.ts
```

每个测试使用独立 chat/user fixture；不能共享真实 `.env` token。初始基座先验证当前既有 migrations 可在临时库运行；`02a` 再增加 sequence 回填 fixture。内部 Agent 调用用本地 mock server 或 fetch mock，覆盖 200、403、5xx、timeout。

## 命令与验收

```powershell
cd D:\project\AI-QA-Assistant\web
pnpm install
pnpm test
pnpm run typecheck
pnpm run lint
```

测试应验证临时库从 migration 创建、suite 之间无数据泄露、失败时清理资源。若 `drizzle-orm/libsql/migrator` 与当前包版本不兼容，停止并报告确切导入错误；不可绕过 migration 直接手建表。
