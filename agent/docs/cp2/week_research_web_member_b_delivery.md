# CP2 Deep Research Web 接入成员 B 交付说明

## 1. 交付结论

成员 B 已完成 Deep Research Web 产品闭环，并在独立 Mock 验证完成后接入现有 Agent Research API。

用户现在可以从首页、对话页或侧边栏显式进入 Deep Research，提交研究问题与本地资料范围，查看并审批 Research Plan，观察 Job 阶段与 Task 进度，并在完成后查看、复制或下载 Markdown 报告。

```text
Explicit Deep Research Entry
→ Create Research Job
→ Planning
→ Plan Review
→ Approve Plan Version + Manifest Hash
→ Poll Durable Job State
→ Stage Timeline + Task Progress + Counters
→ completed / complete or degraded
→ Markdown Report + Evidence Index
```

普通 Chat 保持独立。只有 Deep Research 开关开启时，提交动作才会转入 `/research/new`；普通提交继续使用原 Chat 链路。

---

## 2. 成员 B 完成内容

### 2.1 前端契约

新增完整 TypeScript Contract，覆盖：

- `ResearchRequest`；
- `ResearchJob`；
- `ResearchPlan`；
- `ResearchTask`；
- `ResearchApprovalRequest`；
- `ResearchReport`；
- Job、Task 和 Result 枚举；
- Stage Definition 和 UI Stage Status。

前端只消费现有后端字段，不修改后端 Research Contract。

### 2.2 API Client

新增 Research API Client，正式接入：

```text
POST /api/research/jobs
GET  /api/research/jobs/{research_id}
GET  /api/research/jobs/{research_id}/plan
POST /api/research/jobs/{research_id}/approve
POST /api/research/jobs/{research_id}/cancel
GET  /api/research/jobs/{research_id}/report
```

通过以下环境变量配置：

```env
VITE_RESEARCH_API_BASE=http://127.0.0.1:8000
VITE_RESEARCH_USE_MOCK=false
```

### 2.3 独立 Mock Flow

`VITE_RESEARCH_USE_MOCK=true` 时，不需要启动 Agent，即可独立演示：

```text
created
→ planning
→ awaiting_approval
→ ready
→ execute_tasks
→ coverage
→ generate_claims
→ structural_verification
→ semantic_verification
→ render_report
→ finalize
→ completed
```

Mock 使用与后端一致的 `research.v2` Job、Plan 和 Report 结构，并模拟 Task、Evidence 计数推进。

### 2.4 Research 创建页

新增 `/research/new`：

- Research Query；
- 文档 ID；
- Topic；
- Report Title；
- Language；
- Include Citations；
- Include Limitations；
- User Notes；
- 提交禁用和错误状态。

### 2.5 Plan Review

`awaiting_approval` 时展示：

- Objective；
- Plan Version；
- Manifest Hash；
- Task 顺序；
- Task Dependency；
- Acceptance Criteria；
- Priority；
- Action Budget；
- Approve 和 Cancel。

审批提交严格绑定：

```text
plan_version + manifest_hash
```

### 2.6 Execution Visibility

执行页面展示：

- 整体 Progress；
- 当前 Stage；
- Stage Timeline；
- Task Total / Completed；
- Current Task；
- Evidence Count；
- Claim Count 兼容字段；
- Cancel；
- 刷新后按 `research_id` 恢复。

当前后端尚未提供独立 `/progress` 和 `/events` Endpoint，因此本轮以权威 `ResearchJob.current_stage`、Task 计数和 Evidence 计数生成视图。未来新增 Progress API 时，不需要修改页面主流程。

### 2.7 Polling

- 默认约 1.6 秒轮询；
- 页面隐藏时降低频率；
- 页面离开时停止；
- completed / failed / cancelled 时停止；
- 审批后重新启动；
- 临时查询失败不会清空已显示 Job；
- 页面刷新后重新从 Agent 查询。

### 2.8 Report

完成后展示：

- `complete / degraded`；
- Markdown Report；
- Claim Count；
- Evidence Index；
- Generated Time；
- Copy；
- Markdown Download；
- New Research。

### 2.9 Failure State

已覆盖：

- Agent 不可用；
- Job 404；
- Plan 暂未生成；
- Approval Conflict；
- failed + failure_stage + error_code；
- cancelled；
- completed 但 Report 暂未可读；
- 重复提交和重复审批禁用。

---

## 3. 主要文件

```text
web/src/types/research.ts
web/src/utils/research.ts
web/src/mocks/research.ts
web/src/composables/useResearchApi.ts
web/src/composables/useResearchPolling.ts
web/src/components/research/ResearchForm.vue
web/src/components/research/ResearchPlanReview.vue
web/src/components/research/ResearchProgress.vue
web/src/components/research/ResearchReport.vue
web/src/pages/research/new.vue
web/src/pages/research/[id].vue
```

修改入口：

```text
web/src/pages/index.vue
web/src/pages/chat/[id].vue
web/src/layouts/default.vue
web/.env.example
web/README.md
```

---

## 4. 验证结果

### 4.1 新增代码 ESLint

```text
PASS
0 errors
```

### 4.2 新增代码 TypeScript

对 Research 新增文件进行定向 Typecheck：

```text
PASS
0 Research-related errors
```

仓库全量 Typecheck 仍存在历史错误，包括旧 Topic/Dialog 组件的 Nuxt UI 类型、`server/utils/drizzle.ts`、`useBffChat.ts` 缺失模块等；本轮未修改这些文件。

### 4.3 Client Production Build

```text
PASS
3934 modules transformed
Research /new 和 /:id chunks 已生成
```

Nitro Server Build 在 Client Build 完成后被既有错误阻断：

```text
server/routes/api/chats/[id]/branch.post.ts
imports generateTopicTitle from server/utils/soul.ts
but generateTopicTitle is not exported
```

该错误不属于本轮 Research 变更。

### 4.4 Agent Research Regression

```text
python -m pytest -q \
  tests/integration/test_research_control_plane_api.py \
  tests/integration/test_research_vertical_slice_e2e.py

PASS
```

### 4.5 浏览器 Mock Full Flow

使用本地 Vite 和浏览器完成：

```text
/research/new
→ 填写固定问题
→ 创建 Mock Job
→ 自动进入 Plan Review
→ Approve
→ 展示 ready / executing Progress
→ 自动推进到 completed
→ 展示 Markdown Report 和 Evidence Index

PASS
```

浏览器控制验收同时发现并修复了 Research Dashboard Panel 未显式占满内容区的问题。

---

## 5. 当前边界

- 后端没有 `/progress` 聚合接口；
- 后端没有 Research Event API；
- Claim Count 当前没有进入 `ResearchJob`，页面使用兼容占位；
- 当前资料选择使用 Document ID / Topic 输入，尚未连接可浏览的文档目录 API；
- 本轮使用 polling，不实现 SSE；
- Evidence Index 当前展示稳定 ID，后端尚未提供面向 Web 的 Evidence Detail Endpoint；
- Mock 数据保存在当前浏览器运行内存中，正式页面刷新恢复依赖持久化 Agent API；
- Nitro 全量构建需先修复仓库既有 `generateTopicTitle` 导出问题。

---

## 6. 下一步建议

下一轮优先级：

```text
P0  修复 Nitro 既有构建错误
 ↓
P0  增加后端 Research Progress API
 ↓
P0  增加可浏览的 Source Scope 选择接口
 ↓
P1  增加 Research Events + Recent Activity
 ↓
P1  增加 Evidence Detail API 和原文定位 Drawer
 ↓
P1  Progress Contract 稳定后增加 SSE
```
