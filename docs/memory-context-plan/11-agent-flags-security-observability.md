# 11-Agent 开关、安全与脱敏可观测性

## 目标、前置与施工位置

为 Agent Memory policy 增加可验证的默认关闭开关、无 Redis 的配置拒绝和不含正文的观测事件。此单元不
创建数据库、HTTP route、日志后端或发布环境配置。

前置：`04`、`05`、`07`、`09-Agent`、`09-Web` 均审查通过。后续：`11-Web`、`12`。负责人：Agent。

```text
唯一工作区：D:\project\AI-QA-Assistant-agent-memory
唯一分支：agent-dev-infra
```

允许修改：

- `agent/agent/config/settings.py`
- `agent/agent/agent.py`
- `agent/agent/memory/context_resolver.py`
- `agent/agent/memory/compaction_planner.py`
- 新建 `agent/agent/memory/memory_observability.py`
- `agent/agent/memory/fact_proposal_policy.py`
- `agent/tests/unit/test_internal_memory_contract.py`
- `agent/tests/unit/test_context_resolver.py`
- `agent/tests/unit/test_compaction_planner.py`
- `agent/tests/unit/test_fact_proposal_policy.py`
- 新建 `agent/tests/unit/test_memory_observability.py`
- `agent/docs/API_CONTRACT.md`（仅内部开关/脱敏事件说明）
- `agent/.env.example`

禁止修改 `app.py`、所有 API route、Runtime lifecycle/runner、ToolExecutor、Deep Research、Web 文件、
公开 ChatResponse 或任何真实监控/Redis SDK。若开关接线需要这些热点文件，停止并报告。

## 固定配置与行为

所有值从环境变量读取，默认如下；本单元同步更新 `agent/.env.example` 为安全默认/空占位，绝不写入真实
token：

```text
PERSISTENT_MEMORY_ENABLED=false
SESSION_FACT_ENABLED=false
MEMORY_CACHE_ENABLED=false
MEMORY_TAIL_MESSAGES=8
MEMORY_COMPACTION_MIN_MESSAGES=12
MEMORY_COMPACTION_SOFT_TOKENS=1000
AGENT_INTERNAL_TOKEN=""
```

| 条件 | Agent 必须行为 |
| --- | --- |
| `PERSISTENT_MEMORY_ENABLED=false` | ContextResolver 不处理 trusted persistent context；保持旧 ConversationMemory 路径；internal chat 维持固定 409。 |
| `SESSION_FACT_ENABLED=false` | 不生成 Fact proposal、不执行 deterministic Fact recall、ContextArtifact 的 memory brief 不含 Fact；Snapshot/Tail 仍可按 persistent gate 工作。 |
| `MEMORY_CACHE_ENABLED=true` | Settings/启动配置校验抛出不含秘密的 `memory_cache_not_supported`，服务不得就绪；不得 import Redis。 |
| Resolver/Planner/Fact policy 异常 | 当前 Chat response 继续；返回空 proposal/不推进 plan；只记录枚举 outcome。 |

`MEMORY_TAIL_MESSAGES`、`MEMORY_COMPACTION_MIN_MESSAGES` 与 `MEMORY_COMPACTION_SOFT_TOKENS` 必须以
settings 注入相应 resolver/planner；不得散落硬编码 8/12/1000。所有数值必须为正整数。internal token
缺失/错误仍由 04a 固定 403 处理；本单元不得改变 header、HTTP status 或 token 比较方式。

## 脱敏事件合同

新增纯内存/日志适配层只能接受以下枚举与数值：

```text
memory_resolve { source: disabled|trusted_context|legacy, outcome: success|fallback|rejected, duration_ms }
memory_compaction { outcome: skipped|planned|conflict|failed, tail_count, snapshot_version? }
memory_fact { action: proposed|suppressed|recalled, outcome: success|disabled|sensitive|empty|failed }
memory_prompt { model_history_chars }
```

禁止参数：Fact value、Snapshot summary、Tail、query、完整 prompt、source message ID、token、原始 chat ID。
如需关联，只允许由调用方传入既有 trace ID 或已哈希的 chat identifier；helper 自身不得计算或记录正文。
异常日志只记录事件类型、异常 class 和安全 trace ID，不能传 `exc_info` 中可能含用户正文的对象。

## 有序实施步骤

1. 保留 `09-Agent` 已引入的 `SESSION_FACT_ENABLED=false`，在 Settings 增加其余缺失开关和正整数校验；
   默认全部安全关闭，并测试 `MEMORY_CACHE_ENABLED=true` 失败。
2. 将已有 Resolver/Planner 的 8/12/1000 改为显式 settings 注入；禁止改变 07 算法与 summary 内容。
3. 将 Session Fact gate 接到 candidate policy、Fact recall 和 memory brief 三处，确保关闭时 Facts 不可见但
   Snapshot/Tail 不被误关。
4. 新建无正文 observability helper；在 Agent Memory 的成功/安全降级边界调用，不修改 Runner 日志格式。`memory_prompt` 只能记录实际送往 Runner 的持久 Memory `model_history` 字符数，必须是非负整数；不得记录 query、完整 Prompt 或任意正文。
5. 针对关闭、错误、cache 误开、Fact/recall gate、config 边界和事件 payload 写测试；其中必须验证 `memory_prompt` 只在 Runner 实际执行、且 trusted persistent Context 存在时发出。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant-agent-memory\agent
..\.venv\Scripts\python.exe -m pytest tests/unit/test_internal_memory_contract.py tests/unit/test_context_resolver.py tests/unit/test_compaction_planner.py tests/unit/test_fact_proposal_policy.py tests/unit/test_memory_observability.py tests/integration/test_internal_memory_routes.py
..\.venv\Scripts\python.exe scripts/check_contract.py
```

完成条件：全部通过；默认 settings 不访问 persistent Fact；cache 误开无法启动；事件测试证明没有正文参数；
公开 response 和 04a token contract 无变化；Deep Research 不被导入。

停止并报告：需要 Redis 依赖、需要改变 HTTP route/Runtime、无法在不记录正文的前提下观测、或者 Web/Agent
对开关语义不一致。交接给 11-Web 的内容是六个环境变量、每个 gate 的枚举结果和事件字段。
