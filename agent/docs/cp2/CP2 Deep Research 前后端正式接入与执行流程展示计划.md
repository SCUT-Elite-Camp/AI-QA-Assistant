# CP2 Deep Research 前后端正式接入与执行流程展示计划

## 1. 本轮目标

当前项目已经完成 Local Deep Research Core Vertical Slice：

```text
Manual Create
→ Freeze SourceManifest
→ Generate and Validate Plan
→ User Approval
→ Durable Dispatcher
→ Worker
→ Observation
→ Verified Evidence
→ Finding
→ Coverage
→ Claim
→ Verification
→ Markdown Report
→ completed / degraded
```

本轮不重做 Research Intelligence 和 Runtime 核心链路，而是把已有能力正式接入 Web，形成用户可以完整操作、观察和理解的产品闭环：

```text
用户显式开启 Deep Research
→ 提交研究问题与资料范围
→ 查看并审批 Research Plan
→ 查看 Research 执行流程
→ 查看阶段、任务、证据和结论计数
→ 查看完成、降级、失败或取消结果
→ 阅读最终 Markdown 报告与引用
```

本轮最重要的交付不是单独的进度条，而是建立一套前后端共享、可持久化、刷新后可恢复的 Research Progress Contract。

---

## 2. 本轮范围

### 2.1 P0 必须完成

- Web 端 Deep Research 入口真正创建 Research Job；
- Research 创建表单与资料范围选择；
- Research Plan 查看与审批；
- Job 状态轮询；
- Research 阶段流程展示；
- Task 级基础进度展示；
- Evidence、Claim、Task 计数展示；
- completed / complete 与 completed / degraded 区分展示；
- failed / cancelled 状态与错误阶段展示；
- 最终 Markdown Report 和引用展示；
- 页面刷新后根据 `research_id` 恢复当前状态；
- 前后端正式集成 E2E；
- 不影响现有普通 Chat 链路。

### 2.2 P1 尽量完成

- 用户主动取消 Research Job；
- 最近执行事件列表；
- 阶段开始时间、结束时间和耗时；
- 重复审批、重复取消和重复轮询保护；
- Research 历史入口或最近任务入口；
- 报告复制和 Markdown 下载。

### 2.3 本轮明确不做

- Web Research；
- 并行 Worker；
- 自动 Replan；
- 复杂多 Agent；
- SSE Replay；
- WebSocket；
- Word / PDF 导出；
- 新增 Research 工具；
- 修改现有 Evidence 可信边界；
- 把普通 Chat 自动路由为 Deep Research；
- 多租户权限体系；
- PostgreSQL 或外部消息队列迁移。

---

## 3. 核心原则

### 3.1 Deep Research 必须由用户显式触发

普通 `/api/chat` 不根据模型判断自动创建 Research Job。只有用户显式开启 Deep Research 并提交表单，Web 才调用 Research API。

### 3.2 前端不推断后端业务状态

阶段顺序、阶段名称、当前阶段、计数和错误信息由后端 Progress Contract 返回。前端只负责展示，不根据零散字段重新构建业务状态机。

### 3.3 Progress 必须可恢复

进度不能只存在于浏览器或进程内存中。刷新页面、重新打开页面或应用重启后，必须能够从 SQLite 中恢复。

### 3.4 先轮询，后实时推送

本轮使用低频轮询完成产品闭环。轮询契约稳定后，下一轮可以在不改变页面数据模型的前提下增加 SSE。

### 3.5 本轮不进行中间集成

Day 1 只冻结共享契约、Fixture 和边界，不连接双方实现。

Day 2 至 Day 4：

- A、B 独立开发；
- 不合并对方未完成代码；
- 不连接真实前后端；
- 不进行临时 Vertical Integration；
- A 通过后端 Contract Test、Repository Test 和 API Test 验证；
- B 通过固定 JSON Fixture、Mock API 和组件测试验证；
- 共享契约如需变更，必须修改契约文档和 Fixture，并由双方确认，禁止口头漂移。

Day 5 才进行唯一一次正式集成。

---

## 4. A、B 责任边界

## A：Research Progress Backend

A 负责回答：

> 已有 Research Runtime 如何稳定地产生、保存并对外返回用户可理解的执行进度。

主要负责：

- Progress Contract；
- Stage Definition；
- Job / Stage / Task 状态聚合；
- Research Event 数据结构；
- Research Event Repository；
- Runtime Stage Event 接入；
- Worker Task Event 接入；
- Progress Service；
- Progress API；
- Events API；
- 错误信息映射；
- 计数聚合；
- 后端 Contract Test；
- Repository Test；
- API Test；
- 后端集成 Fixture。

A 不负责：

- Vue 页面；
- UI 组件；
- 浏览器轮询；
- 前端路由；
- 页面视觉样式；
- 修改普通 Chat 页面业务。

## B：Research Web Experience

B 负责回答：

> 用户如何创建、审批、观察并最终阅读一次 Deep Research。

主要负责：

- Deep Research Web 路由；
- Research API Client；
- TypeScript Contract；
- Research 创建表单；
- Source Scope 选择交互；
- Plan Review；
- Approval 交互；
- Progress Timeline；
- Task Progress；
- Counters；
- Job 轮询；
- 页面刷新恢复；
- Error / Cancelled / Degraded 展示；
- Markdown Report 和 Citation 展示；
- Mock API；
- 固定 JSON Fixture；
- 组件测试；
- 前端 Build、Typecheck 和 Lint。

B 不负责：

- 修改 Research Runtime；
- 修改 SQLite Research Repository；
- 在前端重建后端状态机；
- 自行定义与后端不一致的 Stage；
- 自动触发 Research；
- 实现 SSE 或 WebSocket。

## 共同负责

- Day 1 Contract Review；
- API 路径与字段冻结；
- Stage 文案冻结；
- Fixture Review；
- Day 5 正式集成；
- Full E2E；
- 失败场景验收；
- 普通 Chat 回归；
- 最终演示和交付说明。

---

## 5. 共享契约冻结

Day 1 结束前必须冻结以下内容，Day 2 至 Day 4 原则上不再修改。

### 5.1 复用现有 API

```text
POST /research/jobs
GET  /research/jobs/{research_id}
GET  /research/jobs/{research_id}/plan
POST /research/jobs/{research_id}/approve
POST /research/jobs/{research_id}/cancel
GET  /research/jobs/{research_id}/report
```

### 5.2 新增 API

```text
GET /research/jobs/{research_id}/progress
GET /research/jobs/{research_id}/events?after_event_id={event_id}&limit={limit}
```

本轮不新增 SSE Endpoint。

### 5.3 Progress Response

```json
{
  "schema_version": "research.progress.v1",
  "research_id": "research-example",
  "status": "researching",
  "result_status": null,
  "current_stage": "semantic_verification",
  "progress_percent": 72,
  "task_total": 3,
  "task_completed": 3,
  "evidence_count": 8,
  "claim_count": 4,
  "started_at": "2026-09-01T10:00:00Z",
  "updated_at": "2026-09-01T10:00:12Z",
  "stages": [
    {
      "key": "execute_tasks",
      "label": "执行研究任务",
      "status": "completed",
      "started_at": "2026-09-01T10:00:02Z",
      "completed_at": "2026-09-01T10:00:08Z"
    },
    {
      "key": "semantic_verification",
      "label": "验证研究结论",
      "status": "running",
      "started_at": "2026-09-01T10:00:11Z",
      "completed_at": null
    }
  ],
  "tasks": [
    {
      "task_id": "task-1",
      "question": "定位核心事实",
      "status": "succeeded",
      "evidence_count": 3
    }
  ],
  "error": null
}
```

### 5.4 Event Response

```json
{
  "schema_version": "research.events.v1",
  "research_id": "research-example",
  "events": [
    {
      "event_id": 12,
      "event_type": "stage_started",
      "stage": "semantic_verification",
      "task_id": null,
      "message": "正在验证研究结论",
      "payload": {},
      "created_at": "2026-09-01T10:00:11Z"
    }
  ],
  "next_after_event_id": 12
}
```

### 5.5 Stage Definition

阶段顺序固定为：

```text
created
planning
awaiting_approval
ready
execute_tasks
coverage
generate_claims
structural_verification
semantic_verification
render_report
finalize
completed
```

用户文案固定为：

| Stage | 用户文案 |
| --- | --- |
| `created` | 已创建研究任务 |
| `planning` | 正在生成研究计划 |
| `awaiting_approval` | 等待确认研究计划 |
| `ready` | 研究任务等待执行 |
| `execute_tasks` | 正在执行研究任务 |
| `coverage` | 正在检查资料覆盖度 |
| `generate_claims` | 正在整理研究结论 |
| `structural_verification` | 正在检查引用完整性 |
| `semantic_verification` | 正在验证研究结论 |
| `render_report` | 正在生成研究报告 |
| `finalize` | 正在完成研究任务 |
| `completed` | 研究已完成 |

### 5.6 Progress 规则

- `progress_percent` 只用于用户感知，不代表准确剩余时间；
- 已完成阶段不得在正常执行中回退；
- `awaiting_approval` 不自动增长；
- `failed` 和 `cancelled` 保留失败或取消前的最后进度；
- `completed` 必须为 `100`；
- `degraded` 是结果质量，不是执行失败；
- 前端不得根据数组下标自行计算百分比；
- 未开始时间使用 `null`，禁止伪造时间；
- Error 不返回 Python 堆栈和敏感路径。

---

## 6. 独立开发策略

## A 的独立验证方式

A 使用 FastAPI TestClient 和临时 SQLite 完成：

```text
Create Job
→ Dispatcher Planning
→ Approve
→ Dispatcher Execution
→ Query Progress
→ Query Events
→ Query Report
```

A 不依赖 Web 启动。

## B 的独立验证方式

B 使用 Day 1 冻结的 JSON Fixture 模拟以下状态：

```text
created
planning
awaiting_approval
ready
researching / execute_tasks
researching / semantic_verification
synthesizing / render_report
completed / complete
completed / degraded
failed
cancelled
```

B 不依赖 Agent 服务启动。

## 共享 Fixture

建议新增：

```text
agent/mock/research_web_contract/
├── create_job.json
├── awaiting_approval.json
├── approved_ready.json
├── progress_researching.json
├── progress_synthesizing.json
├── progress_completed.json
├── progress_degraded.json
├── progress_failed.json
├── progress_cancelled.json
├── events.json
└── report.json
```

A 的 API Contract Test 和 B 的 Mock API 必须读取同一组 Fixture 或由同一份 Schema Fixture 派生，防止双方各自维护一套示例。

---

## 7. 五天并行安排

| 时间 | A：Research Progress Backend | B：Research Web Experience | 集成规则 |
| --- | --- | --- | --- |
| Day 1 | Progress/Event Contract、Stage Definition、Fixture Schema | 页面状态机、路由设计、TS Contract、交互原型 | 只冻结契约，不接真实接口 |
| Day 2 | Event Repository、Progress Service Skeleton、API Skeleton | 创建页、Plan Review、Approval Mock Flow | 双方独立测试，不集成 |
| Day 3 | Runtime Stage Event、Worker Task Event、计数聚合 | Progress Timeline、Task List、轮询与恢复 | 双方独立测试，不集成 |
| Day 4 | Error/Cancel/Degraded、后端 Contract/API Tests | Report/Citation、异常状态、前端质量门禁 | 双方独立收口，不集成 |
| Day 5 | 支持真实接口联调、修复后端契约问题 | 切换真实 API、修复前端联调问题 | 唯一正式集成日，完成 Full E2E |

---

## 8. 每日详细计划

## Day 1：Contract Freeze

### A 任务

1. 定义 `ResearchProgress`；
2. 定义 `ResearchStageProgress`；
3. 定义 `ResearchTaskProgress`；
4. 定义 `ResearchEvent`；
5. 定义 `ResearchEventType`；
6. 固定 Stage 顺序和用户文案；
7. 固定 Progress 计算规则；
8. 固定 Error Response；
9. 生成共享 JSON Fixture；
10. 编写 Schema Contract Test。

### B 任务

1. 设计 `/research/new`；
2. 设计 `/research/:id`；
3. 定义页面状态机；
4. 根据冻结 JSON 编写 TypeScript 类型；
5. 定义 API Client Interface；
6. 设计创建、审批、执行、报告四种主视图；
7. 确认现有 Deep Research 开关的跳转行为；
8. 设计移动端和桌面端基本布局；
9. 设计 Loading、Empty、Error 状态；
10. 建立 Mock API 数据入口。

### Day 1 Gate

- A/B 对 API、字段、枚举、Stage 文案无歧义；
- JSON Fixture 可被 Python 和 TypeScript 读取；
- 未连接真实前后端；
- Day 2 后不再随意修改共享字段。

---

## Day 2：Control Surface

### A 任务

1. 新增 `research_events` 表；
2. 增加事件索引；
3. 实现事件幂等写入策略；
4. 实现按 `research_id` 查询事件；
5. 实现 `after_event_id` 增量查询；
6. 实现 Progress Service Skeleton；
7. 聚合现有 Job、Task、Checkpoint 和实体计数；
8. 增加 `/progress` API；
9. 增加 `/events` API；
10. 完成 Repository Unit Test。

### B 任务

1. 实现 Research 创建页面；
2. 实现 Query 输入；
3. 实现 Source Scope 选择；
4. 实现提交、禁用和错误状态；
5. 实现 Plan Review；
6. 展示 Task、依赖、Acceptance Criteria；
7. 实现 Approve 按钮；
8. 实现 Cancel 按钮基础交互；
9. 使用 Mock 完成创建到审批流程；
10. 防止重复提交和重复审批。

### Day 2 Gate

A 必须证明：

```text
Fixture Job + Events
→ Progress Service
→ research.progress.v1
```

B 必须证明：

```text
Mock Create
→ Mock Planning
→ Mock Awaiting Approval
→ Plan Review
→ Mock Approve
→ Ready View
```

双方仍不连接真实服务。

---

## Day 3：Execution Visibility

### A 任务

1. 在 Job 创建和规划阶段记录事件；
2. 在 Approval 成功后记录事件；
3. 在 `ResearchGraphRuntime._stage()` 接入阶段事件；
4. 在 Worker Task 开始时记录 Task Event；
5. 在 Worker Task 完成或失败时记录 Task Event；
6. 聚合 `task_total` 和 `task_completed`；
7. 聚合 `evidence_count`；
8. 聚合 `claim_count`；
9. 记录 Stage 时间；
10. 验证重启恢复后事件不重复或可安全去重。

### B 任务

1. 实现总进度展示；
2. 实现阶段 Timeline；
3. 实现 running / completed / pending / failed 样式；
4. 实现 Task List；
5. 实现 Evidence、Claim 和 Task 计数；
6. 实现最近事件列表；
7. 实现 1～2 秒轮询；
8. 页面离开后停止轮询；
9. terminal status 后停止轮询；
10. 页面刷新后根据路由 `research_id` 恢复。

### Day 3 Gate

A 使用后端测试证明完整 Runtime 会持续产生可查询进度。

B 使用 Mock 时间序列证明页面可从：

```text
ready
→ execute_tasks
→ coverage
→ generate_claims
→ verification
→ render_report
```

连续更新，且不依赖真实 Agent 服务。

---

## Day 4：Quality and Failure Closure

### A 任务

1. 完成 completed / complete；
2. 完成 completed / degraded；
3. 完成 failed；
4. 完成 cancelled；
5. 映射 `failure_stage` 和安全错误信息；
6. 验证取消后状态不继续推进；
7. 验证恢复后 Progress 正确；
8. 验证 Report 已落库但未 Finalize 的恢复场景；
9. 完成 API Contract Test；
10. 完成后端 Regression Test。

### B 任务

1. 实现 Markdown Report 展示；
2. 实现 Citation / Evidence 索引展示；
3. 区分 complete 和 degraded；
4. 展示资料限制；
5. 展示失败阶段和错误信息；
6. 展示 cancelled；
7. 实现报告复制；
8. 完成 Responsive 基础检查；
9. 完成 Typecheck、Lint 和 Build；
10. 完成 Mock Full Flow。

### Day 4 Gate

A 的交付必须能够独立通过：

```text
Schema Test
Repository Test
Progress Service Test
Research API Test
Research Vertical Slice Regression
```

B 的交付必须能够独立通过：

```text
Mock Complete Flow
Mock Degraded Flow
Mock Failed Flow
Mock Cancelled Flow
Typecheck
Lint
Build
```

Day 4 结束后双方停止新增功能，只保留 Day 5 集成修复。

---

## Day 5：唯一正式集成日

### 集成顺序

严格按照以下顺序，不并行修改共享契约：

```text
1. 启动 Agent Research API
2. 用 HTTP 脚本验证现有 Research API
3. 验证新增 Progress / Events API
4. Web 从 Mock API 切换到真实 API
5. 跑通 Create
6. 跑通 Planning / Awaiting Approval
7. 跑通 Approve
8. 跑通 Progress Polling
9. 跑通 Report
10. 验证 Error / Cancel / Degraded
11. 回归普通 Chat
12. 完成最终演示和交付文档
```

### A 任务

- 保证 Agent 服务可启动；
- 修复真实数据与冻结 Contract 的差异；
- 修复 Progress 聚合问题；
- 修复 Event 幂等和状态问题；
- 提供固定本地资料演示输入；
- 配合 E2E 定位后端问题；
- 不在集成日增加新能力。

### B 任务

- 切换真实 API Base URL；
- 修复 CORS、Header 和错误解析；
- 修复轮询停止条件；
- 修复真实 Markdown / Citation 展示；
- 修复刷新恢复；
- 配合 E2E 定位前端问题；
- 不在集成日修改产品范围。

### Day 5 Gate：Full Product Vertical Slice

必须从浏览器完整跑通：

```text
打开 Web
→ 显式开启 Deep Research
→ 输入研究问题
→ 选择本地资料
→ 创建 Research Job
→ 自动等待 Planning
→ 查看 Research Plan
→ 审批 Plan Version + Manifest Hash
→ 查看阶段持续推进
→ 查看 Task 与 Evidence 计数
→ Research completed
→ 查看 Markdown Report
→ 查看引用与资料限制
```

---

## 9. 前端页面设计

### 9.1 `/research/new`

包含：

- Research Query；
- Source Scope；
- Report Language；
- Report Title；
- Include Citations；
- Include Limitations；
- Submit；
- Validation Error。

### 9.2 `/research/:id`

同一路由根据后端状态展示不同内容：

| Job 状态 | 主视图 |
| --- | --- |
| `created` / `planning` | Planning Loading |
| `awaiting_approval` | Plan Review |
| `ready` | Waiting for Execution |
| `researching` | Research Progress |
| `synthesizing` | Research Progress + Report Preparing |
| `completed` | Research Report |
| `failed` | Failure State |
| `cancelled` | Cancelled State |

### 9.3 建议组件

```text
web/src/components/research/
├── ResearchForm.vue
├── ResearchPlanReview.vue
├── ResearchProgress.vue
├── ResearchStageTimeline.vue
├── ResearchTaskList.vue
├── ResearchEventList.vue
├── ResearchCounters.vue
├── ResearchReport.vue
├── ResearchResultBadge.vue
└── ResearchErrorState.vue
```

### 9.4 建议 Composable

```text
web/src/composables/
├── useResearchApi.ts
├── useResearchJob.ts
└── useResearchPolling.ts
```

---

## 10. 后端设计

### 10.1 建议模块

```text
agent/agent/schemas/research.py
agent/agent/api/research_routes.py
agent/deep_research/progress.py
agent/deep_research/events.py
agent/deep_research/repository.py
agent/deep_research/runtime.py
agent/deep_research/worker.py
```

### 10.2 Event Persistence

建议字段：

```text
event_id INTEGER PRIMARY KEY AUTOINCREMENT
research_id TEXT NOT NULL
event_key TEXT NOT NULL
event_type TEXT NOT NULL
stage TEXT
task_id TEXT
message TEXT NOT NULL
payload_json TEXT NOT NULL
created_at TEXT NOT NULL
UNIQUE(research_id, event_key)
```

`event_key` 用于恢复和重放时幂等。例如：

```text
{research_id}:stage:coverage:started:attempt-0
{research_id}:task:task-1:completed:attempt-0
{research_id}:report:ready:{report_id}
```

### 10.3 Progress 聚合来源

```text
ResearchJob       → status / current_stage / result_status / error
ResearchPlan      → task_total
ResearchTask      → task status
ResearchEvent     → stage timing / recent activity
Evidence Ledger   → evidence_count
Claim Repository  → claim_count
ResearchReport    → report readiness
```

Progress 是读模型，不替代现有业务对象，也不成为第二份业务真相。

---

## 11. 测试矩阵

| 场景 | 后端断言 | 前端断言 |
| --- | --- | --- |
| 创建 Job | 返回 created 和 research_id | 跳转到 Research 详情页 |
| Planning | Progress 返回 planning | 展示生成计划中 |
| Awaiting Approval | Plan 可查询 | 展示 Plan 和 Approve |
| Version Conflict | 409 + 稳定错误码 | 提示计划已变化并刷新 |
| Researching | Stage 和 Task 持续推进 | Timeline 和计数更新 |
| Refresh | Progress 可恢复 | 页面恢复当前阶段 |
| Complete | progress=100，Report 存在 | 展示完整报告 |
| Degraded | completed + degraded | 展示资料不足或冲突提示 |
| Failed | failure_stage 和安全错误 | 展示失败阶段和说明 |
| Cancelled | terminal cancelled | 停止轮询并展示取消状态 |
| Restart Recovery | Event 不重复，状态继续 | 页面无需特殊处理 |
| Report Recovery | Report 不重复 | 最终只展示一份报告 |
| Chat Regression | `/api/chat` 行为不变 | 普通 Chat 可继续使用 |

---

## 12. 质量门禁

### 后端门禁

- Existing Research Unit Tests 全部通过；
- Existing Research Integration Tests 全部通过；
- 新增 Progress Contract Tests 通过；
- 新增 Event Repository Tests 通过；
- 新增 Progress API Tests 通过；
- Restart Recovery 不产生重复业务实体；
- API 不暴露堆栈、绝对路径或敏感配置；
- 普通 Chat Baseline 不回归。

### 前端门禁

- TypeScript Typecheck 通过；
- ESLint 通过；
- Production Build 通过；
- 页面刷新可恢复；
- Terminal Status 停止轮询；
- 重复按钮有防抖或 disabled；
- 空字段、404、409、500 不白屏；
- complete / degraded / failed / cancelled 视觉上可区分；
- 普通 Chat 页面无回归。

### 集成门禁

- 浏览器 Full Product Vertical Slice 通过；
- 至少一个 complete Fixture 通过；
- 至少一个 degraded Fixture 通过；
- 至少一个 failed 或 cancelled Fixture 通过；
- Agent 重启后页面可以继续查询；
- 前后端字段与 Day 1 Contract 一致；
- 最终 Demo 不依赖手工修改 SQLite。

---

## 13. 风险与控制

### 风险 1：Day 5 才发现 Contract 不一致

控制：

- Day 1 冻结共享 JSON；
- A 的响应测试使用共享 Fixture；
- B 的 Mock 使用同一 Fixture；
- 所有枚举值逐项列出；
- Day 2 至 Day 4 禁止双方私自增加字段语义。

### 风险 2：现有 Task Status 没有在 Worker 中完整更新

控制：

- Progress 第一优先使用已有权威对象；
- Task 级状态缺失时通过 Event 补充展示；
- 不为了 UI 重写 Worker；
- Task 级进度不影响 Job 级完成判定。

### 风险 3：重启恢复产生重复 Event

控制：

- Event 增加稳定 `event_key`；
- Repository 使用唯一约束；
- Runtime 重放只允许幂等写入；
- Event 不作为业务执行的唯一依据。

### 风险 4：轮询造成不必要压力

控制：

- 默认 1500～2000ms；
- 页面隐藏时降低频率或暂停；
- terminal status 立即停止；
- `/progress` 使用聚合查询，不读取大段 Evidence 原文和报告正文。

### 风险 5：Day 5 集成时间不足

控制：

- Day 4 前双方必须各自完成 Full Mock Flow；
- Day 5 禁止新增需求；
- 先完成 P0 主链，再处理 P1；
- 如 Events UI 阻塞，保留 Progress Timeline，事件列表降级为 P1；
- 如 Task 级计数阻塞，保证 Stage 级进度和最终报告优先完成。

---

## 14. Day 5 缺陷优先级

```text
P0  无法创建 Research Job
 ↓
P0  无法查看或审批 Plan
 ↓
P0  Job 执行但页面无法恢复进度
 ↓
P0  completed 后无法展示 Report
 ↓
P0  普通 Chat 回归
 ↓
P1  Task 状态或计数不精确
 ↓
P1  Event 列表缺失
 ↓
P1  视觉和动效问题
```

Day 5 不允许用新增功能掩盖 P0 缺陷。

---

## 15. Definition of Done

本轮只有满足以下全部条件才算完成：

- 用户可以从 Web 显式创建 Deep Research；
- 用户可以查看 Research Plan；
- 用户审批的是明确的 `plan_version + manifest_hash`；
- 后端在后台执行，不阻塞创建请求；
- Web 可以持续展示当前阶段；
- Web 可以展示基础 Task 进度和实体计数；
- 页面刷新后能够恢复当前 Job；
- complete 和 degraded 被正确区分；
- failed 和 cancelled 有明确用户反馈；
- completed 后可以查看 Markdown Report；
- Report 引用可以定位到 Evidence 信息；
- Restart Recovery 后前端仍可继续查询；
- 普通 Chat 不会自动创建 Research Job；
- 普通 Chat 的既有能力没有回归；
- 后端、前端和 E2E 测试通过；
- 最终演示从浏览器开始，不依赖命令行补步骤；
- Day 1 至 Day 4 未进行真实前后端中间集成；
- Day 5 完成唯一一次正式集成并形成交付记录。

---

## 16. 最终演示脚本

固定演示问题：

> 比较 Alpha 与 Beta 的部署状态，并给出原文依据。

固定资料：

```text
project-alpha
project-beta
```

演示过程：

1. 从 Web 首页显式开启 Deep Research；
2. 输入固定问题；
3. 选择两份固定资料；
4. 创建 Job；
5. 展示 Planning；
6. 展示 Plan、Task 依赖和资料范围；
7. 审批 Plan；
8. 展示执行阶段持续推进；
9. 展示 Task、Evidence 和 Claim 计数；
10. 展示 Report 生成；
11. 展示 completed / complete；
12. 打开 Markdown Report；
13. 展示引用定位；
14. 刷新页面，证明结果仍然存在；
15. 补充演示 degraded 或 failed 固定 Fixture。

最终用户可见链路：

```text
正在生成研究计划
→ 等待你确认研究计划
→ 正在执行研究任务
→ 正在检查资料覆盖度
→ 正在整理研究结论
→ 正在检查引用完整性
→ 正在验证研究结论
→ 正在生成研究报告
→ 研究完成
```
