# CP2 Day 3–4 A 侧交付说明

本次只完成 Research Intelligence，不改 Control Plane，也不提交 PR。

## 交付内容

| 计划项 | 实现位置 | 说明 |
|---|---|---|
| Worker Strategy | `deep_research/worker.py` | 依赖真实 `ApprovedResearchContext`，按 Plan 依赖顺序执行有界 Search→Read |
| Observation / Evidence | `deep_research/worker.py` | Search 只写 Observation，Original Read 成功后才写 VerifiedEvidence |
| Finding / Criterion Mapping | `deep_research/worker.py` | Evidence 生成 Finding，保守映射 `covers`，无证据不生成 Finding |
| Coverage | `deep_research/coverage.py` | 只做 Required Criterion 的 covered/missing 聚合 |
| Claim-first | `deep_research/claims.py` | Finding → ClaimDraft，不从自由报告反向抽事实 |
| Semantic Verification | `deep_research/verifier.py` | 提供统一 Protocol、确定性基线和 Fixture Mock |
| Markdown Renderer | `deep_research/renderer.py` | 只接收 VerifiedClaim、Coverage、Evidence 索引和限制说明，不调用工具 |
| Quality Fixture | `mock/research_day3_day4_cases.json` | 单文档、双文档、资料不足、证据冲突四类 Case |

## Worker 入口约束

Worker 不接受裸 Query、裸 Plan 或客户端拼装的数据作为执行入口。

```python
context = control_plane.claim_for_execution(research_id)
result = LocalResearchWorker(tools, ledger).run(context)
```

`context` 同时包含：

```text
context.job       # ResearchJob，已进入 researching
context.plan      # 已批准的 ResearchPlan
context.tasks     # Repository 中的真实 ResearchTask
context.manifest  # 冻结 SourceManifest
context.approval  # 绑定 plan_version + manifest_hash 的 Approval
```

Worker 启动前会再次校验这些对象的 `research_id`、Plan 版本、Manifest hash、
Approval 状态和 Task 内容一致性。

## 单 Task 策略

```text
Task
 ↓ 1 action
Search
 ↓
Observation
 ↓ 每次 Read 占 1 action
Original Read
 ↓
VerifiedEvidence
 ↓
Finding
```

硬约束：

- Task 依赖由已批准 Plan 拓扑排序；
- 只执行一个 Worker，不执行并行；
- `task.source_ids` 必须属于 SourceManifest；
- Search Snippet 不直接成为 Evidence；
- Read 缺少 Locator 或原文时不会生成 Evidence；
- 每个 Task 遵守 `max_actions`，不会无界循环；
- 依赖 Task 未成功时，后继 Task 标记为 `blocked`。

## 报告链路

```text
Finding
  ↓
ClaimGenerator
  ↓
ClaimDraft
  ↓
Structural Verification（B 侧）
  ↓
SemanticVerifier（A 侧）
  ↓
VerifiedClaim
  ↓
MarkdownReportRenderer
  ↓
ResearchReport
```

Renderer 的安全边界：

- `supported` Claim 才能作为确定性结论输出；
- `partial` Claim 必须带“部分证据支持”表述；
- `conflicting` Claim 必须披露冲突；
- `unsupported` Claim 不进入确定性正文，只进入局限性；
- Renderer 没有 Search / Read Tool，也不会创建新的 Claim 或 Evidence。

## 测试

```powershell
..\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_research_worker_reporting.py -q
..\.venv\Scripts\python.exe -m pytest -q
```

当前分支只保留本地实现，未推送、未创建 PR。
