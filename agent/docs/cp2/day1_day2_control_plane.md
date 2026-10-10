# CP2 Day 1–2 Control Plane 交付说明

## 目标

本次交付完成 Core Vertical Slice 的控制面，不实现 Worker。后续 Worker
必须从 `ApprovedResearchContext` 获取真实的：

```text
ResearchJob
ResearchPlan
ResearchTask
SourceManifest
ResearchApproval
```

Worker 不应通过用户请求、模型输出或 Graph State 自行拼接这些对象。

## 已交付模块

| 模块 | 位置 | 作用 |
|---|---|---|
| Runtime Contract v2 | `agent/schemas/research.py` | Job、Manifest、Approval、Task 及后续 Evidence/Claim 对象 |
| SourceManifest Resolver | `deep_research/manifest.py` | 从本地文档目录或测试 Catalog 冻结文档版本与 hash |
| SQLite Repository | `deep_research/repository.py` | 唯一业务状态真相，持久化 Job、Manifest、Plan、Task、Approval |
| Control Plane | `deep_research/service.py` | 创建 Job、生成 Plan、审批绑定、取消和执行上下文校验 |
| Planner | `deep_research/planner.py` | 当前使用确定性的 Mock Planner，生成最多 3 个串行 Task |
| Durable Dispatcher | `deep_research/dispatcher.py` | 基于 SQLite 的 ready Job claim；未注入 Worker 时不虚假改变状态 |
| HTTP API | `agent/api/research_routes.py` | 创建、查询、查看 Plan、批准、取消 |

## 控制面流程

```text
POST /api/research/jobs
    ↓
SQLite INSERT ResearchJob(created)
    ↓
解析并冻结 SourceManifest
    ↓
生成并校验 ResearchPlan + ResearchTask
    ↓
ResearchJob(awaiting_approval)
    ↓
POST /api/research/jobs/{id}/approve
    ↓
Approval(plan_version + manifest_hash)
    ↓
ResearchPlan(approved) + ResearchJob(ready)
```

批准时会同时校验：

1. Job 当前仍为 `awaiting_approval`；
2. `plan_version` 等于当前 Plan 版本；
3. `manifest_hash` 等于当前冻结 Manifest；
4. Plan 与 Manifest 的 hash 一致。

Approval、Plan 状态和 Job=`ready` 在一个 SQLite 事务中提交。

## 后续 Worker 接口

```python
context = control_plane.claim_for_execution(research_id)

context.job       # ResearchJob，状态为 researching
context.plan      # 已批准的 ResearchPlan
context.tasks     # 该 Plan 的真实 ResearchTask
context.manifest  # 冻结的 SourceManifest
context.approval  # 精确绑定 Plan 与 Manifest 的 ResearchApproval
```

`claim_for_execution()` 会先重新校验 Approval、Plan、Manifest 和 Job 的一致性，
然后原子地把 `ready` Job 置为 `researching`。因此后续 Worker 的入口天然受审批
和来源范围约束。

## API

```text
POST /api/research/jobs
GET  /api/research/jobs/{research_id}
GET  /api/research/jobs/{research_id}/plan
POST /api/research/jobs/{research_id}/approve
POST /api/research/jobs/{research_id}/cancel
```

创建请求只允许提交 `query`、本地 `source_scope` 和 `report_spec`。用户身份从
`X-User-ID` 请求头读取，不允许客户端在 JSON 中伪造 `user_id`。

## 测试

新增控制面单元与 API 测试，覆盖：

- SQLite 重启后 Job、Plan、Task、Manifest 仍存在；
- 旧 Plan Version 不能审批；
- 错误 Manifest Hash 不能审批；
- 未审批 Job 不会被 Dispatcher claim；
- 已审批 Job 只能被 claim 一次；
- 搜索范围中的外部 URL 会被拒绝。

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```
