# 11 功能开关、安全、隐私与可观测性

## 目标

让 Persistent Memory 可独立关闭、失败可降级、可定位问题且不泄露个人内容。首版不实现 Redis，但预留 `MEMORY_CACHE_ENABLED=false` 配置，禁止任何 Redis 客户端依赖。

前置：`01`、`04`、`05`、`07`、`09`。负责人：Web + Agent。后续依赖：`12`、`13`。

## 配置

Agent 设置新增并验证：

```text
PERSISTENT_MEMORY_ENABLED=false
SESSION_FACT_ENABLED=false
MEMORY_CACHE_ENABLED=false
MEMORY_TAIL_MESSAGES=8
MEMORY_COMPACTION_MIN_MESSAGES=12
MEMORY_COMPACTION_SOFT_TOKENS=1000
AGENT_INTERNAL_TOKEN=<required for trusted memory input>
```

Web 配置新增：`PERSISTENT_MEMORY_ENABLED=false`、`SESSION_FACT_ENABLED=false`、`AGENT_BASE_URL`、`AGENT_INTERNAL_TOKEN`。部署时 Web 与 Agent 的 persistent 开关必须相同；若 Agent 私有端点返回 `persistent_memory_disabled`，BFF 记录不含正文的配置错误并仅回退一次公开 `/api/chat`。所有秘密只存在环境变量；`.env.example` 只给空值或占位符。

## 降级矩阵

| 情况 | 行为 |
| --- | --- |
| Persistent 开关关闭 | 原 `ConversationMemory` 短窗路径 |
| 未登录 | 普通聊天/短窗；不读写 Snapshot/Fact |
| Agent persistent 开关关闭 | 私有 chat 返回固定 409；BFF 仅回退一次公开 chat |
| BFF Memory 查询失败 | 记录安全错误，使用空/短窗上下文继续回答 |
| Agent Resolver/Compactor 失败 | 当前回答继续；不确认 Fact、不推进 Snapshot |
| Fact API 失败 | 显示操作失败；服务端状态不改变 |
| Redis 开关误开 | 启动/配置校验拒绝，直到后续独立 Redis 单元批准 |

## 指标和日志

可记录：`memory_resolve_total{source,outcome}`、Tail 条数、Snapshot version、compaction attempted/succeeded/conflict/failed、Fact proposal/confirm/revoke count、deterministic recall count、fallback count、耗时分布。

绝不记录：Fact value、Snapshot summary、Tail 正文、完整 Prompt、内部 token、用户敏感消息。日志使用 trace ID、chat ID 哈希或受控内部 ID；错误报告也必须脱敏。

## 安全验收

- 缺少/错误内部 token 不能注入 memory_context。
- 开关关闭不会访问 Memory Repository。
- Memory 故障不把用户内容写入异常日志，也不阻断正常问答。
- 生产环境不允许默认 `SESSION_SECRET` 或默认内部 token。
- 回归检查 RAG citations 不引用 Fact。

## 交接

将配置表、指标字典、告警阈值建议交给 `13`；Redis 需求只能在有真实性能数据后另开新施工单。
