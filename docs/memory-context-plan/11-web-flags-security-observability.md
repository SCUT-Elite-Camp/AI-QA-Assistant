# 11-Web 开关、BFF 降级与脱敏可观测性

## 目标、前置与施工位置

在 Web BFF 实施与 11-Agent 完全一致的开关语义、一次性公开 chat 回退、Fact route gate 与无正文指标。
本单元不改 Agent、UI、数据库 schema/migration，也不把任意 Memory 正文交给浏览器或日志。

前置：`09-Web`、`11-Agent` 均审查通过。后续：`12`、`13`。负责人：Web。

```text
唯一工作区：D:\project\AI-QA-Assistant
唯一分支：web-dev
```

允许修改：

- `web/server/utils/agentInternalClient.ts`
- `web/server/utils/persistentMemoryContext.ts`
- `web/server/utils/postTurnCompaction.ts`
- `web/server/utils/metrics.ts`
- `web/server/utils/logger.ts`
- 新建 `web/server/utils/memoryFeatureFlags.ts`
- `web/server/routes/api/chats/[id].post.ts`
- `web/server/routes/api/chats/[id]/memory/facts*.ts` 与其子 route（仅增加 gate）
- `web/.env.example`（若不存在，改为根目录实际受跟踪的环境示例文件并在交接中说明）
- `web/tests/utils/agentInternalClient.test.ts`
- `web/tests/utils/postTurnCompaction.test.ts`
- `web/tests/routes/factLifecycle.test.ts`
- 新建 `web/tests/utils/memoryFeatureFlags.test.ts`

禁止修改 Agent、浏览器 UI、schema/migration、Redis 依赖、公开 ChatResponse、internal HTTP 契约或
`/api/internal/*` 的鉴权。若 `web/.env.example` 不存在且没有受跟踪替代文件，停止，不得新建含秘密文件。

## 固定开关与降级矩阵

Web 只读取服务器环境变量，默认：

```text
PERSISTENT_MEMORY_ENABLED=false
SESSION_FACT_ENABLED=false
MEMORY_CACHE_ENABLED=false
AGENT_BASE_URL=<development only default; production required>
AGENT_INTERNAL_TOKEN=""
```

| 条件 | BFF 行为 |
| --- | --- |
| persistent=false 或 actor 未认证 | 不读取 Memory Repository、不建 trusted context、不调用 internal chat/compaction；走现有公开/短窗路径。 |
| Agent internal chat 返回 409 `persistent_memory_disabled` | 记录 `memory_fallback{reason=agent_disabled}`，仅调用一次公开 chat；不重试 internal endpoint。 |
| Memory context/compaction HTTP、schema 或 Repository 失败 | 当前聊天继续；context 用空/短窗安全降级，compaction/fact proposal 安全跳过；不回滚已持久化助手消息。 |
| session fact=false | 所有 Fact API 在身份/ownership 验证后返回 409 `session_fact_disabled`；BFF 不持久化 Agent proposal，Context 不传 Facts。 |
| cache=true | 启动/首次配置校验抛出 `memory_cache_not_supported`；不得 import/connect Redis。 |

生产环境中缺少 `AGENT_INTERNAL_TOKEN`、`AGENT_BASE_URL` 或安全 session secret 必须保留已有 fail-closed
行为；日志不得输出环境变量。Web 与 Agent persistent/fact 开关是否相同由 `12` 集成测试与 `13` 发布审查
验证，BFF 不得通过远程探测自动改写任一方配置。

## 指标、日志与实现步骤

`metrics.ts` 只能新增不含正文的计数/时长 API，允许：`memory_resolve_total{source,outcome}`、
`memory_compaction_total{outcome}`、`memory_fact_total{action,outcome}`、`memory_fallback_total{reason}`、
`memory_duration_ms{operation}`，以及 tail count/snapshot version 的非负数记录。labels 必须是本文定义的
有限枚举；不得使用 chat ID、Fact ID、source ID、query、summary 或 exception message 作为 label。

1. 将 `09-Web` 的 `sessionFactGate.ts` 纳入新建的纯 `memoryFeatureFlags.ts`，集中解析/校验三个 boolean；
   不改变 Session Fact 默认 false 的语义，cache=true 抛固定安全 error。
2. 将 persistent/fact gates 接到 context 构造、internal-client 选择、compaction 与 Fact routes；不得重复读取
   环境变量或让 UI 传开关。
3. 保留并测试 internal 409 的单次公开回退；其他错误只走一次安全降级，不产生循环请求。
4. 在每个成功/失败边界记录有限指标与脱敏结构化日志；不得把 caught error 原样序列化。
5. 更新受跟踪环境示例，所有默认均为 false/空占位，绝不提交实际 token。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant\web
pnpm exec vitest run tests/utils/agentInternalClient.test.ts tests/utils/postTurnCompaction.test.ts tests/utils/memoryFeatureFlags.test.ts tests/routes/factLifecycle.test.ts
pnpm run typecheck
pnpm run lint
```

完成条件：默认/匿名路径不访问 Repository；409 只回退一次；Fact gate 不能读写；cache=true fail closed；
metric/log payload 测试无正文；公开 ChatResponse 不变；不存在 Redis import。停止并报告：需要真实部署 secret、
Agent 开关语义不一致、错误对象无法安全脱敏、或需修改未列 route/schema。交接给 12 的内容是配置矩阵、
回退测试和指标字典；交接给 13 的内容是默认值与告警建议。
