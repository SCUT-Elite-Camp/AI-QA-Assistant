# 13 发布就绪审查、授权灰度与交接

## 目标、前置与权限边界

本单元首先完成**不改变外部环境**的发布就绪审查、回滚 Runbook 和交接材料。它不是部署授权：任何
push、测试环境开关、灰度用户选择、部署、生产查询、真实 token 配置或回滚，均必须由用户在本单元审查
PASS 后另行明确授权。

前置：12 已 PASS，`12-acceptance-report.md` 已审查。负责人：Web/Agent 集成人与负责人。

```text
默认施工位置：D:\project\AI-QA-Assistant（web-dev，只改 docs）
Agent 证据读取位置：D:\project\AI-QA-Assistant-agent-memory（agent-dev-infra，只读）
```

允许修改：`docs/memory-context-plan/13-rollout-and-handoff.md`、新建
`docs/memory-context-plan/evidence/13-release-readiness.md`，以及只读检查两个工作区的 Git/测试报告。
禁止修改业务代码、环境变量文件、密钥、部署配置、远程 Git、数据库或运行中服务。

## 阶段 A：发布就绪审查（可由公式化执行 Prompt 完成）

`13-release-readiness.md` 必须逐项记录并引用 12 的证据：

1. Web/Agent commit、PR/owner review、工作区干净状态与 Agent 写锁 holder；禁止直接 push `dev/main`。
2. 三个默认值：`PERSISTENT_MEMORY_ENABLED=false`、`SESSION_FACT_ENABLED=false`、
   `MEMORY_CACHE_ENABLED=false`；环境示例无 token，Redis 无依赖。
3. 依赖顺序、内部 token 403、public ChatResponse 兼容、Chat/Deep Research 隔离、RAG citation 不来自
   Fact 的测试证据。
4. 指标名称、有限 label、告警观察项：compaction failed/conflict、fallback、403/409、Fact 操作失败、
   prompt length；所有日志不含正文/秘密。
5. 以下回滚 Runbook：persistent 关闭恢复短窗且保留 Snapshot/Fact；Fact 关闭不自动确认 proposal；安全
   疑虑关闭两开关并阻断 Fact API；已执行 migration 仅可 forward migration 或受控备份恢复，禁止手删表。
6. 明确未实现项：Redis、USER Fact、自动确认、自由自然语言 Fact 抽取、生产性能/回答质量 SLA。

完成条件：所有条目有链接/命令证据，12 为 PASS，且交接材料标明 owner 与回滚负责人。若任何项缺失，
13 为 FAIL，不得请求灰度授权。

## 阶段 B：真实灰度（必须由用户单独授权）

在阶段 A PASS 后，执行者必须停止并请求一条包含下列全部信息的明确授权，不能从“执行 13”推断：

```text
我授权在 <环境> 执行 Persistent Memory 灰度：
- 可操作系统/部署命令：<具体范围>
- 允许的开关阶段：persistent only / persistent + session fact
- 灰度用户或流量范围：<范围>
- 观察时长与负责人：<信息>
- 回滚负责人和触发阈值：<信息>
```

获得授权后，仍按最小阶段执行：

1. 所有环境保持三个开关 false；仅在授权测试环境启用 persistent，Fact 仍 false。
2. 验证 Snapshot/Tail、fallback 与无正文指标；失败立即关闭 persistent。
3. 经第二次明确授权才启用 session fact，执行 confirm/revoke/delete/cross-user 验收；失败只关闭 fact。
4. 经第三次明确授权才扩至小范围用户；`MEMORY_CACHE_ENABLED` 始终 false。

每一步记录时间、环境、开关、证据、异常与回滚动作；不得把本地测试成功描述为已上线。

## 最终交接与停止条件

每个提交/PR 描述列明施工单、路径、默认开关、测试、未验证项、回滚、Chat/Deep Research 隔离。施工文档
必须先在 `web-dev` 评审并以 docs-only 提交同步到 `agent-dev-infra`；Agent Memory 只允许以 5955 为祖先的
开发线选择性迁移，保留 lifecycle、ToolExecutor 与 Deep Research。

停止并报告：缺少 12 PASS、无 owner approve、无明确外部授权、无法确认环境开关一致、发生权限/隐私疑虑、
或回滚路径未经演练。未同时满足阶段 A、授权灰度和回滚记录前，项目仍处于实施中，不能宣称完整上线。
