# CP2 Deep Research 本周完整交付与现场演示说明

> 文档日期：2026-09-08
> 当前开发分支：`agent-dev-infra`
> 基线提交：`d2117ba`（合并 PR #35）
> 当前形态：Local Deep Research，真实 Agent API，本地知识库限定范围
> 演示入口：`http://127.0.0.1:3000/`

## 1. 本周交付结论

本周在 PR #35 已有 Deep Research 核心链路之上，完成了面向真实用户的前后端接入和对话式体验改造。

用户不再进入独立的 Research 工具表单，而是在普通 New Chat 输入框中显式选择“深度研究”，选择本地知识库文件并提交研究问题。系统创建 Research Job、冻结 SourceManifest、生成 Research Plan，并在用户确认后执行有界研究。研究过程通过右侧状态栏持续展示，最终报告作为助手回答呈现，并支持原文引用、追问、划词提问、收藏和反馈。

当前可演示的产品闭环为：

```text
New Chat
→ 选择“深度研究”
→ 选择本地知识库文件
→ 输入研究问题
→ 创建 Research Job，并立即获得 research_id
→ 冻结 SourceManifest
→ 生成并校验 Research Plan
→ 用户通过按钮或对话修改、批准计划
→ Durable Dispatcher 调度执行
→ Worker 按依赖运行 Research Task
→ Search 定位候选内容
→ Read Original 扩展并读取原文上下文
→ Observation 转换为 Verified Evidence
→ Finding / Coverage / Claim
→ Structural / Semantic Verification
→ 生成 Markdown Research Report
→ 在同一对话中查看引用、处理冲突并继续追问
```

## 2. 用户可见功能

### 2.1 与普通问答统一的入口

- Deep Research 是 New Chat 输入框下方的显式模式选项；
- 普通问答仍走原 `/api/chat` 链路，不会被自动升级为 Research；
- 选择 Deep Research 后，输入框提示用户输入研究问题并选择本地知识库文件；
- 不保留独立的 Deep Research 侧栏入口；
- Research 会话与普通对话一起出现在左侧历史记录中；
- 点击历史记录能够恢复对应的 Research Job。

### 2.2 人工指定研究资料

- 用户必须从本地知识库目录中选择至少一份文件；
- 系统只把选中文档写入 `source_scope.document_ids`；
- Job 创建时解析并冻结 SourceManifest；
- Planner、Worker 和验证阶段不得访问 Manifest 外资料；
- 当前产品不执行 Web Research，也不把联网来源加入 Evidence；
- 本轮没有修改 `toolset` 检索层和工具层实现。

### 2.3 研究计划与人工审批

- 创建 Job 后后台生成 Plan；
- Plan 展示研究目标、任务、目的、依赖、验收条件和动作预算；
- 用户可以点击按钮批准，也可以在底部对话框回复“批准”；
- 用户可以通过编辑器修改任务并保存为新 Plan Version；
- 用户也可以通过自然语言提出计划修改，例如“把第 2 步改为……”；
- 修改后旧 Plan 标记为 superseded，新 Plan 必须重新审批；
- Approval 同时绑定 `plan_version` 和 `manifest_hash`；
- 未审批的 Plan 不会进入 Worker 执行。

当前正式审批点只有 Plan Approval。执行阶段不会逐任务暂停。报告完成后，如果存在结构化冲突，用户可以通过对话选择来源并生成新的报告修订，但这属于完成后的冲突裁决，不是运行中的 Graph Interrupt。

### 2.4 执行过程展示

右侧 Research 状态栏展示：

- 总进度百分比；
- 当前阶段；
- 已完成任务数 / 总任务数；
- Evidence 数；
- 12 个权威阶段的状态；
- 最近持久化事件；
- 刷新恢复提示。

主对话区域不重复展示完整阶段列表，只保留自然语言状态消息。这样避免主区域与右侧状态栏重复。

### 2.5 对话式 Research

Research 页面底部始终保留输入框，整个过程保持连续对话：

- 计划阶段可以批准或提出修改；
- 执行阶段可以查看状态并取消允许取消的任务；
- 报告完成后可以继续追问；
- 后续回答只使用本次冻结并核验的 Evidence；
- 报告中的文本可以划词并带入底部输入框继续提问；
- 用户可以用自然语言选择冲突来源；
- 用户选择和处理理由会持久化为 Research Event。

### 2.6 报告、引用与反馈

- 最终结果以 Markdown 助手回答展示；
- 报告包含结论摘要、关键发现、逐项分析、冲突、局限和引用；
- 正文中的 `[1]`、`[2]` 会转换为普通问答同款引用标签；
- 引用标签悬停时显示对应 Evidence 原文；
- 长原文支持在浮层中上下滚动；
- 下方使用普通问答同款“已检索知识库”折叠入口；
- 删除了重复的“来源”和“引用与原文”双重列表；
- 报告可下载为 Markdown；
- 报告及 Research 助手回复支持收藏、复制、点赞、点踩、改进建议和重新生成；
- 收藏与赞踩结果持久化，刷新后仍然保留。

## 3. 后端完整流程

### 3.1 创建与冻结

```text
POST /api/research/jobs
→ 校验 ResearchRequest
→ 创建 ResearchJob
→ 返回 research_id
→ 解析本地文档目录
→ 生成 SourceManifest
→ 保存 Manifest Hash
→ 状态进入 planning
```

SourceManifest 保存：

- `doc_id`；
- 标题和来源类型；
- 文档版本；
- 生效时间和更新时间；
- 权威等级；
- 替代关系；
- 内容哈希。

### 3.2 Planning

当前 Planner 分为两层：

1. `ModelResearchPlanner`：使用模型根据问题和冻结文档生成 2～5 个非重复任务；
2. `MockResearchPlanner`：当模型不可用、超时或结果非法时提供确定性三步兜底计划。

所有候选计划都必须通过：

- Schema Validator；
- SourceManifest 范围校验；
- Tool Allowlist；
- Task 数量限制；
- Action Budget；
- 依赖无环校验；
- Plan Version 校验。

当前在线模型统一配置为：

```text
qwen3.7-flash-2026-07-15
```

### 3.3 Approval 与 Revision

```text
Plan v1
→ awaiting_approval
→ 用户批准 plan_version + manifest_hash
→ 保存不可变 Approval Snapshot
→ ready
```

如果用户修改计划：

```text
Plan v1
→ Revision
→ Plan v1 superseded
→ Plan v2 awaiting_approval
→ 用户重新批准 v2
→ ready
```

### 3.4 Research Graph 与 Worker

Graph 按固定有界阶段执行：

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

Worker 按 Plan 依赖拓扑顺序执行任务。每个任务受以下约束：

- 只能使用允许的本地只读工具；
- 只能访问 SourceManifest 中的文档；
- 受 `max_actions` 和整体预算约束；
- 非法依赖和非法循环在执行前被 Validator 拒绝；
- 每个候选命中必须继续读取原文，不能把搜索摘要直接作为 Evidence。

### 3.5 Evidence 链路

```text
Search Hit
→ Observation
→ Read Document Range
→ 扩展命中位置上下文
→ Original Read
→ Verified Evidence
→ Finding
→ Claim
→ Citation
```

每条 Verified Evidence 至少包含：

- `evidence_id`；
- `research_id` 和 `task_id`；
- `doc_id`；
- 文档版本；
- Locator；
- 原文 excerpt；
- 内容哈希。

### 3.6 Coverage 与 Verification

- Coverage 将 Finding 与 Plan 的 Acceptance Criteria 对齐；
- Structural Verification 检查引用完整性、Evidence 绑定和结构约束；
- Semantic Verification 判断 Claim 是否 supported、unsupported 或 conflicting；
- 未得到证据支持的结论不能进入最终报告；
- 冲突和资料缺口必须显式保留；
- 有风险但执行完成的结果标记为 degraded，而不是 failed。

### 3.7 报告生成与追问

- 报告模型基于冻结 Evidence 生成结构化 Markdown；
- 模型失败时保留确定性报告兜底；
- Citation 编号映射到具体 Evidence；
- 报告完成后的追问由 Research Conversation API 处理；
- 追问不得扩展到新的外部来源；
- 冲突裁决会保存用户选择、理由和新的报告修订。

## 4. 持久化、事件与恢复

### 4.1 持久化对象

SQLite 保存：

- ResearchJob；
- SourceManifest；
- ResearchPlan 及历史版本；
- ResearchApproval；
- ResearchTask；
- Observation；
- Verified Evidence；
- Finding；
- Claim；
- Verification；
- ResearchReport；
- ResearchEvent；
- Graph Checkpoint。

### 4.2 事件

当前主要事件包括：

```text
job_created
plan_revised
plan_approved
job_recovered
stage_started
stage_completed
task_started
task_completed
task_failed
task_blocked
report_ready
job_completed
job_failed
job_cancelled
user_message
assistant_message
conflict_resolved
```

事件使用稳定 `event_key` 和数据库唯一约束，保证恢复和重放时不会重复写入。

### 4.3 Checkpoint Recovery

- 服务中断后根据持久化 Job 和 Graph Checkpoint 判断恢复位置；
- 已成功完成的 Stage、Task、Evidence 和 Report 不重复写入；
- 可安全恢复时记录 `job_recovered`；
- 检查点不可信时明确失败，不盲目从头执行；
- Web 刷新后重新请求 Job、Progress、Events、Plan 和 Report。

## 5. 前后端模块说明

### 5.1 Agent / Research 后端

| 模块 | 作用 |
| --- | --- |
| `agent/agent/schemas/research.py` | Research Contract、状态、事件、Plan、Evidence、Report 数据模型 |
| `agent/agent/api/research_routes.py` | Job、Plan、审批、取消、Progress、Events、Report 和对话接口 |
| `agent/deep_research/service.py` | Control Plane、状态迁移、Plan Revision 和 Approval |
| `agent/deep_research/repository.py` | SQLite 持久化、幂等写入和实体查询 |
| `agent/deep_research/planner.py` | 动态 Planner、确定性兜底 Planner 和 Plan Validator 接入 |
| `agent/deep_research/manifest.py` | SourceManifest 解析、冻结和范围约束 |
| `agent/deep_research/dispatcher.py` | 后台 Job 扫描和调度 |
| `agent/deep_research/runtime.py` | Research Graph、阶段推进和恢复 |
| `agent/deep_research/worker.py` | Task 执行、原文读取和 Evidence 生成 |
| `agent/deep_research/pipeline.py` | Search / Read Adapter 与 Research Intelligence Pipeline |
| `agent/deep_research/events.py` | 持久化 Research Event |
| `agent/deep_research/progress.py` | 聚合 Job、Task、Event、Evidence 和 Claim 为 Progress 读模型 |
| `agent/deep_research/verifier.py` | 语义核验和冲突状态 |
| `agent/deep_research/renderer.py` | 结构化 Citation、Conflict、Limitation 与报告渲染 |
| `agent/deep_research/model_report.py` | 基于 Evidence 的模型报告生成 |

### 5.2 Web 前端

| 模块 | 作用 |
| --- | --- |
| `web/src/pages/index.vue` | New Chat 与 Deep Research 统一入口 |
| `web/src/pages/chat/[id].vue` | 已有普通 Chat 入口适配，不改变普通提交主链 |
| `web/src/pages/research/[id].vue` | 对话式 Research 主页面和状态视图 |
| `web/src/components/research/ResearchModeNotice.vue` | 本地知识库文件选择 |
| `web/src/components/research/ResearchPlanReview.vue` | Plan 查看、编辑、审批和取消 |
| `web/src/components/research/ResearchStatusCard.vue` | 右侧阶段、进度、计数和最近活动 |
| `web/src/components/research/ResearchReport.vue` | Markdown 报告、引用、冲突、局限和划词提问 |
| `web/src/components/research/ResearchMessageActions.vue` | 收藏、复制、赞踩、建议和重新生成 |
| `web/src/composables/useResearchApi.ts` | Research API Client 与 Mock/Real 切换 |
| `web/src/composables/useResearchPolling.ts` | 轮询、事件游标、终态停止和刷新恢复 |
| `web/src/composables/useResearchLaunch.ts` | 创建 Job、注册历史记录并跳转 |
| `web/server/routes/api/research/*` | 文档目录、Research Chat 注册及反馈消息持久化 |

## 6. API 清单

### Agent Research API

```text
POST /api/research/jobs
GET  /api/research/jobs/{research_id}
GET  /api/research/jobs/{research_id}/plan
POST /api/research/jobs/{research_id}/plan/revisions
POST /api/research/jobs/{research_id}/approve
POST /api/research/jobs/{research_id}/cancel
POST /api/research/jobs/{research_id}/messages
GET  /api/research/jobs/{research_id}/progress
GET  /api/research/jobs/{research_id}/events
GET  /api/research/jobs/{research_id}/report
```

### Web BFF API

```text
GET  /api/research/documents
POST /api/research/chats
POST /api/research/messages
```

反馈继续复用普通 Chat 的既有接口：

```text
GET  /api/chats/votes/{chat_id}
POST /api/chats/votes/{chat_id}
POST /api/messages/{message_id}/feedback
```

## 7. A、B 分工与本周实际变化

### 成员 A：Research Intelligence / Progress Backend

原分工主要包括：

- Research Contract；
- Planner 和 Validator；
- Worker 决策；
- Finding、Coverage、Claim；
- Structural / Semantic Verification；
- Report Renderer；
- Progress/Event Contract 与后端测试。

### 成员 B：Research Runtime / Web Experience

本周主要交付：

- Research API 和 Web 正式接入；
- 对话式 Deep Research 入口；
- Source Scope 文件选择；
- Plan Review、修改和审批交互；
- 状态轮询和刷新恢复；
- 右侧 Research 状态栏；
- 报告、Citation 和 Evidence 原文展示；
- Research 对话历史接入；
- 报告追问、划词提问和冲突裁决交互；
- 点赞、点踩、收藏、复制和改进建议；
- 在线联调与演示准备。

### 共同边界

- Planner Input / Output；
- SourceManifest 和 Evidence Contract；
- API 字段和状态枚举；
- Full E2E；
- 普通 Chat 回归；
- 最终现场演示。

当前工作区为完成在线闭环，已经在 PR #35 基础上增加了动态 Planner、报告模型和 Research 对话接口。这些改动跨越了原本的纯 Web 责任边界，提交前需要 A、B 共同 Review。

## 8. 当前验证结果

### 已验证

- 本地前端运行在 `127.0.0.1:3000`；
- Agent Research API 运行在 `127.0.0.1:8000`；
- `VITE_RESEARCH_USE_MOCK=false`；
- 浏览器真实创建、审批、执行和报告链路已经跑通；
- 模型报告真实生成；
- Research 历史记录可以恢复；
- 引用标签可以关联 Evidence excerpt；
- 收藏、点赞和点踩状态刷新后保持；
- `toolset` 目录没有本轮改动。

### 当前质量门禁

截至 2026-09-08 的最新只读验证结果：

```text
Agent tests: 374 passed, 2 failed
Frontend typecheck: failed
Frontend lint: failed（20 errors, 244 warnings）
Frontend production build: blocked by Turso migration authToken configuration
```

两个 Agent 回归失败分别涉及：

1. 政策冲突 Demo 的计划文本断言；
2. 冲突 Evidence 预期 `conflicting`，实际为 `unsupported`。

因此，本周功能闭环可以现场展示，但当前工作区尚不能宣称全部质量门禁通过。

## 9. 已知限制与后续工作

### P0：正式提交前必须处理

- 修复两个 Agent 回归失败；
- 修复 Research 页面新增的 TypeScript 错误；
- 明确 Turso 本地 migration 配置，恢复 Production Build；
- 复核当前大量未提交文件，只提交本周范围内变更；
- A、B Review 动态 Planner 和报告模型的责任边界。

### P1：产品体验改进

- Planner 失败时不要无提示展示固定模板，应明确显示“计划生成已降级”并允许重试；
- 在普通问答引用浮层中补回版本、生效时间、权威等级和内容哈希；
- 右侧状态栏补充 Task 级详情和 Claim 数；
- 增加真正的运行中取消；
- 对证据不足、来源冲突和扩大资料范围增加条件式审批点；
- 为报告重新生成设计正式的 Report Revision API。

### 当前明确不做

- Web Research；
- 自动把普通 Chat 路由为 Deep Research；
- 并行 Worker；
- 多 Agent 协作；
- SSE / WebSocket；
- Word / PDF 导出；
- 修改底层检索和工具实现。

## 10. 现场演示方案

### 10.1 推荐演示目标

现场演示重点不是“模型回答得更长”，而是证明：

> 用户能够限定研究资料、审批研究计划、观察持久执行，并核对每个结论所依据的本地原文。

### 10.2 演示前准备

1. 确认 Agent `.env` 中所有 Research 模型均为 `qwen3.7-flash-2026-07-15`；
2. 确认 `web/.env`：

   ```text
   VITE_RESEARCH_API_BASE=http://127.0.0.1:8000
   VITE_RESEARCH_USE_MOCK=false
   ```

3. 启动 Agent：

   ```powershell
   cd D:\htc_qa\agent
   D:\miniconda3\envs\htc_project\python.exe app.py
   ```

4. 启动 Web：

   ```powershell
   cd D:\htc_qa\web
   npm run dev
   ```

5. 打开 `http://127.0.0.1:3000/`；
6. 确认本地知识库中存在演示文档；
7. 提前跑一遍完整流程，避免首次模型请求和本地模型冷启动影响演示；
8. 保留一个已完成 Research 历史记录，作为网络或模型异常时的只读备份。

### 10.3 推荐主演示：Agent CP1 / CP2 演进

选择资料：

```text
cp1_cp2_architecture_overview
cp2_development_plan
cp2_final_handoff
cp2_integration_contract
```

研究问题：

```text
基于所选本地项目文档，梳理 Agent 层从 CP1 到 CP2 的架构和能力演进，比较核心流程、模型路由、证据约束与恢复机制，并指出目前仍未完成或缺少数据验证的部分。所有结论必须引用原文。
```

这组问题能够展示：

- 多文档研究；
- 动态任务拆解；
- 架构比较；
- 原文 Evidence；
- 局限说明；
- 报告后的继续追问。

### 10.4 备用演示：政策冲突核验

选择资料：

```text
星云科技差旅管理办法（旧版）
星云科技差旅管理办法（现行版）
财务报销 FAQ（待同步页面）
```

研究问题：

```text
核验上海酒店 650 元/晚能否报销。员工出差日期为 2026 年 9 月 10 日，已取得直属经理审批。请比较正式办法和财务 FAQ 的住宿限额、版本和生效时间，指出冲突并给出可核验结论。
```

该场景更适合展示：

- 版本冲突；
- 来源权威性；
- 生效时间；
- degraded 与 failed 的区别；
- 用户对话裁决冲突；
- 报告修订。

## 11. 现场演示逐步脚本

### 第 1 步：统一入口

操作：打开 New Chat，选择“深度研究”。

讲解：

> Deep Research 和普通问答使用同一个入口，但只有用户显式选择后才创建 Research Job，不会由模型自动切换。

### 第 2 步：选择本地资料

操作：展开资料选择器，选择演示文档。

讲解：

> 当前只研究人工选定的本地知识库文件。提交后系统会冻结 SourceManifest，执行过程中不能偷偷扩大来源范围。

### 第 3 步：创建 Job

操作：输入研究问题并发送。

讲解：

> 创建接口立即返回 research_id，后台继续规划。Research 会话同时进入普通对话历史，刷新或重新打开都可以恢复。

### 第 4 步：查看和修改计划

操作：展示 Plan 的任务、依赖和验收条件；通过对话输入：

```text
把第 2 步改为重点比较 CP1 和 CP2 的证据约束、纠正检索与失败回退机制。
```

讲解：

> 修改不会覆盖旧计划，而是生成 Plan v2。旧批准不能沿用，必须重新确认新版本和同一份 Manifest。

### 第 5 步：批准

操作：回复“批准”，或点击“批准并开始研究”。

讲解：

> Worker 在审批前不能执行。Approval 绑定 Plan Version 和 Manifest Hash，防止执行用户没有确认过的计划或资料。

### 第 6 步：观察执行

操作：让观众看右侧状态栏连续变化。

讲解：

> 前端不自行猜测进度，所有阶段、计数和事件都来自后端持久化 Progress Contract。服务或页面中断后可以从 Checkpoint 和数据库恢复。

重点指出：

```text
执行任务
→ 检查资料覆盖度
→ 整理结论
→ 检查引用完整性
→ 验证结论
→ 生成报告
```

### 第 7 步：查看报告与原文

操作：报告完成后悬停正文引用编号，展开“已检索知识库”。

讲解：

> 搜索结果本身不是证据。Worker 会继续读取原文范围，保存 Locator、版本、原文 excerpt 和内容哈希，最终结论只能引用已核验 Evidence。

### 第 8 步：连续对话

操作：选择一段报告文字，点击“划词提问”，继续追问：

```text
这项结论具体由哪段原文支持？是否还有适用条件？
```

讲解：

> Research 不是一次性报告页面，而是一段持续对话。后续回答仍限定在本次已经冻结和核验的 Evidence 内。

### 第 9 步：反馈与收藏

操作：演示收藏、复制、点赞、点踩和建议弹窗。

讲解：

> Research 回复复用普通对话的反馈能力，反馈会持久化，刷新后仍然保留。

### 第 10 步：刷新恢复

操作：刷新浏览器页面。

讲解：

> 页面会根据 research_id 重新读取 Job、Plan、Progress、Events 和 Report，不依赖浏览器内存恢复状态。

## 12. 三分钟讲解稿

> 本周我们把已经完成的 Local Deep Research 核心链路正式接入了前后端。用户现在从普通 New Chat 选择深度研究模式，人工指定本地知识库资料并提交问题。系统会立即创建 Research Job、返回 research_id，并冻结本次允许访问的 SourceManifest。
>
> 系统随后生成一个有依赖、有验收条件和动作预算的 Research Plan。用户可以查看、修改并批准计划；修改会生成新版本，旧审批不能继续使用。审批通过后，Durable Dispatcher 启动 Research Graph，Worker 按任务依赖执行本地搜索和原文读取，将工具结果统一转成可定位、可校验的 Evidence，再完成 Coverage、Claim 和两阶段验证。
>
> 执行过程中的阶段、任务和证据状态由后端持久化并在右侧状态栏展示，刷新或服务中断后可以恢复。最终报告作为同一段对话中的助手回答呈现，引用能够定位到本地原文，用户还能划词追问、处理冲突、收藏、赞踩和提交改进建议。
>
> 与普通问答相比，它的核心价值不是回答更长，而是研究范围可控、计划经过确认、执行过程可恢复、结论能够回溯原文，并且不会隐藏冲突和资料不足。

## 13. 演示故障预案

### 计划生成回退到固定模板

说明：模型 Planner 调用失败后会使用确定性计划，链路仍可执行，但计划文案会偏通用。

处理：重新创建一次 Job；如果仍失败，使用固定计划继续展示范围冻结、审批、执行和证据链，不宣称该计划由模型动态生成。

### 模型报告生成较慢

处理：等待右侧 `render_report` 阶段完成；不要刷新后重复创建 Job。必要时打开预先完成的 Research 历史记录。

### 报告标记为 degraded

说明：degraded 不是系统失败，而是存在冲突、证据不足或无法确认事项。

处理：展示冲突和局限，再通过底部对话框追问或选择来源。这通常比只展示 complete 更能体现 Deep Research 的价值。

### 前端页面无法加载

依次确认：

1. Web 端口 3000 是否正常；
2. Agent `/health` 或 Research Job API 是否正常；
3. `VITE_RESEARCH_API_BASE` 是否指向 8000；
4. 是否误开 `VITE_RESEARCH_USE_MOCK=true`；
5. 浏览器控制台是否存在 BFF 或 CORS 错误。

## 14. 演示验收清单

演示前逐项确认：

- [ ] 当前分支和提交范围正确；
- [ ] Agent 8000 端口启动；
- [ ] Web 3000 端口启动；
- [ ] Research Mock 已关闭；
- [ ] 模型额度可用；
- [ ] 本地知识库目录可读取；
- [ ] 演示文档可以被资料选择器看到；
- [ ] 创建 Job 后能立即获得 research_id；
- [ ] Plan 能生成并展示；
- [ ] Plan 修改后版本递增；
- [ ] 批准后状态开始推进；
- [ ] 右侧阶段和 Evidence 数持续变化；
- [ ] 最终报告可以生成；
- [ ] 引用标签能显示原文；
- [ ] 底部输入框可以继续追问；
- [ ] 收藏和赞踩刷新后保留；
- [ ] 刷新页面后报告仍存在；
- [ ] 已准备一个完成态备份 Job；
- [ ] 已知质量门禁问题已向评审方如实说明。

## 15. 本周交付边界总结

本周已经完成的是一条可实际操作和在线展示的 Local Deep Research 产品链路：

```text
显式开启
+ 人工限定本地资料
+ Job/Plan/Approval 持久化
+ 有界 Graph 执行
+ Evidence 原文链路
+ 执行状态展示
+ Checkpoint 恢复
+ Markdown 报告
+ 引用与冲突
+ 连续对话
+ 用户反馈
```

当前尚未达到“可以无条件合并发布”的质量状态。正式提交前仍需修复回归测试与前端质量门禁，并对跨越 A/B 原责任边界的动态 Planner、模型报告和对话接口进行共同 Review。
