# 12 测试与验收施工单

## 目标

建立从纯函数、Repository、BFF、Agent 到流式完成时序的回归证据。通过测试只代表当前本地环境和覆盖场景，不代表生产性能或回答质量。

前置：`01` 至 `11` 及 `12a`。负责人：各单元 owner；最终由集成人汇总。

## 必须新增的测试组

### Web/数据库

- migration：空库、已有库、外键级联、索引与唯一约束；
- chat access：跨用户、匿名、公开 chat、伪造 user ID；
- lifecycle：sequence 单调、重试幂等、取消/错误不写助手；
- mutation：编辑/重生成 revision 失效、branch 隔离、删除清理；
- Fact routes：proposal/confirm/revoke 的所有权、状态迁移、过期。

### Agent

- 先运行 `06a` 锁定的 `5955cd0` Week-1 Runtime 回归，证明 `ApplicationContainer`、lifespan、`get_agent()`、`/ready`、工具执行路径未被 Memory 回退；
- resolver：Snapshot/Tail 边界、Fact 可见性、长度上限、开关回退、注入文本隔离；
- prompt：当前 query 一次、RAG system 约束仍在、CitationChecker 回归；
- recall policy：明确回忆命中/不命中、普通问题不触发；
- compaction planner：8 条 Tail、12 条阈值、旧摘要增量、敏感排除、冲突计划。
- route/container：三条 internal endpoint 的 token 负向路径、409 开关路径、FastAPI dependency override 复用 `get_agent()`，且不创建第二个 Agent。
- isolation：Chat、`/api/internal/chat`、compaction 与 reset 不导入、创建、读取或修改 `agent/deep_research/**` 的 Research Job/状态。

### 跨层

在两个职责明确的工作目录中（Web `D:\project\AI-QA-Assistant`，Agent `D:\project\AI-QA-Assistant-agent-memory`）用 mock Agent/Repository 或真实本地服务证明：

```text
用户消息落库 -> trusted context -> Agent answer -> 流成功
-> 助手消息落库 -> compaction plan -> Snapshot 持久化
```

额外验证服务重启后由数据库恢复、Memory 失败降级、无 cross-user Fact 泄露。

## 运行与报告

Web 使用 `12a` 固定的 Vitest + 临时 libSQL 数据库。除单元测试外，至少运行：

```powershell
cd D:\project\AI-QA-Assistant\web
pnpm run db:generate
pnpm run db:migrate
pnpm run typecheck
pnpm run lint
```

Agent 使用以 `5955cd0` 为冻结代码祖先（可叠加 docs-only 同步提交）的 `agent-dev-infra` 工作目录上的项目 Python/venv，先运行该分支实际提供的 Week-1 runner，再运行目标 pytest 模块及全量 pytest：

```powershell
Set-Location D:\project\AI-QA-Assistant-agent-memory
python agent\scripts\run_week1_tests.py
python -m pytest agent\tests
```

若项目 Python 不是 `python`，仅替换解释器路径，不改变 runner 和测试范围。若环境不存在，报告准确命令和失败原因；不得编造成功。运行前后记录 `git show --no-patch --format=%H HEAD`，防止把旧 `web-dev` 的测试结果当作新版 Runtime 的证据。

每个测试报告应写：commit、环境、命令、通过/失败数、未运行项、真实限制。性能测试和 Redis 不在本单元范围。

## 验收门槛

- 无阻断性迁移问题；公开 ChatResponse 兼容；
- Snapshot/Tail 跨重启恢复；
- 只使用 Confirmed、未过期、同 revision SESSION Fact；
- 编辑/删除后不再读取旧记忆；
- Memory 任一故障可降级；
- 所有权/内部 token 负向测试通过。
- Agent 侧 `ApplicationContainer`/lifecycle/工具执行器回归通过，且 Chat Memory 与 Deep Research 严格隔离。

未满足任何一项，停止发布并回到对应单元修复。
