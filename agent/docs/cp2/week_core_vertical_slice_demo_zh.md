# CP2 Deep Research 本周成果与展示效果

## 1. 本周最终实现了什么

本周完成了第一条可运行、可持久、可追溯的 Local Deep Research 核心链路。

用户需要手动创建研究任务，并明确选择本地资料。系统冻结资料版本、生成研究计划，等待用户审批；审批通过后，后台执行研究任务，通过搜索定位候选内容、读取原文、生成可信证据，再完成结论生成、覆盖度检查和两阶段验证，最终输出带引用的 Markdown 报告。

```text
手动创建 Research Job
  → 冻结 SourceManifest
  → 生成并校验 Research Plan
  → 用户审批 Plan Version + Manifest Hash
  → Durable Dispatcher 领取任务
  → Worker 按依赖顺序执行
  → Search 生成 Observation
  → Original Read 生成 Verified Evidence
  → Finding
  → Acceptance Criteria Coverage
  → Claim Draft
  → Structural Verification
  → Semantic Verification
  → Markdown Report
  → completed / complete 或 completed / degraded
```

这条 Research 链路与普通 Chat 隔离。普通 `/api/chat` 不会自动创建 Research Job，也不会因为模型输出了 “research” 就进入长任务流程。

---

## 2. 完整案例：比较 Alpha 与 Beta 的部署状态

下面用一个具体任务贯穿本周实现的完整链路。这个例子不是只展示最终报告，而是逐步说明系统在每个阶段收到了什么、生成了什么、保存了什么，以及为什么需要该步骤。

### 2.1 准备固定本地资料

本次研究只允许使用两份本地文档。

`project-alpha.json`：

```json
{
  "doc_id": "project-alpha",
  "title": "项目 Alpha 状态",
  "version": "v1",
  "content": "项目 Alpha 的部署状态为已完成。\n部署验收记录已归档。"
}
```

`project-beta.json`：

```json
{
  "doc_id": "project-beta",
  "title": "项目 Beta 状态",
  "version": "v1",
  "content": "项目 Beta 的部署状态为已完成。\n部署验收记录已归档。"
}
```

这两份资料位于固定目录：

```text
agent/mock/research_documents/
```

固定资料的作用是让演示结果可重复。系统不会联网，也不会在运行过程中临时加入第三份资料。

### 2.2 用户创建 Research Job

用户提出问题：

> 比较 Alpha 与 Beta 的部署状态，并给出原文依据。

请求内容：

```json
{
  "query": "比较 Alpha 与 Beta 的部署状态，并给出原文依据",
  "source_scope": {
    "document_ids": [
      "project-alpha",
      "project-beta"
    ]
  }
}
```

系统首先只创建一个持久化任务，并立即返回：

```json
{
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "status": "created",
  "current_stage": "created",
  "task_total": 0,
  "task_completed": 0,
  "evidence_count": 0,
  "result_status": null
}
```

此时还没有执行 Search，也没有调用 Worker。立即返回的意义是：Research 是后台长任务，创建接口不需要阻塞到报告生成结束。

状态变化：

```text
无任务 → created
```

### 2.3 Dispatcher 发现待规划任务

Durable Dispatcher 每隔固定时间扫描 SQLite 中的待处理 Job。

它发现状态为 `created` 的任务后，将任务交给规划流程：

```text
created → planning
```

Dispatcher 不是一次性的内存队列。即使应用在创建任务后退出，任务仍然保存在 SQLite 中；应用重新启动后，Dispatcher 还可以再次发现它。

### 2.4 冻结 SourceManifest

系统根据用户提交的 `source_scope` 查找两份文档，并为每份文档记录：

- `doc_id`；
- `version`；
- `content_hash`。

生成的 SourceManifest 可以理解为：

```json
{
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "documents": [
    {
      "doc_id": "project-alpha",
      "version": "v1",
      "content_hash": "alpha-content-hash"
    },
    {
      "doc_id": "project-beta",
      "version": "v1",
      "content_hash": "beta-content-hash"
    }
  ],
  "manifest_hash": "8a5599e8d44944d6e4d1d563aea17ab79b8a4d18e75287adf3ad1f90b073e0a1"
}
```

这里的 `alpha-content-hash` 和 `beta-content-hash` 是为了便于阅读的缩写；实际系统保存完整哈希。

SourceManifest 冻结后，后续 Planner、Worker、Structural Verifier 都只能使用其中的文档。这样可以回答一个重要问题：

> 最终报告究竟基于哪个版本的哪些资料生成？

如果运行过程中 `project-alpha` 内容发生变化，Original Read 重新计算出的哈希与 Manifest 不一致，系统会拒绝把变化后的内容作为当前任务的 Evidence。

### 2.5 生成 Research Plan

Planner 根据研究目标和冻结资料生成三个有依赖关系的任务。

#### Task 1：定位核心事实

```json
{
  "task_id": "task-1",
  "question": "定位与研究目标直接相关的原始事实：比较 Alpha 与 Beta 的部署状态，并给出原文依据",
  "dependencies": [],
  "allowed_tools": [
    "keyword_search",
    "read_document_range"
  ],
  "source_ids": [
    "project-alpha",
    "project-beta"
  ],
  "max_actions": 4
}
```

#### Task 2：核验原文位置

```json
{
  "task_id": "task-2",
  "question": "读取并核验候选事实对应的原始文档位置。",
  "dependencies": ["task-1"],
  "allowed_tools": [
    "keyword_search",
    "read_document_range"
  ],
  "max_actions": 4
}
```

#### Task 3：整理结论和限制

```json
{
  "task_id": "task-3",
  "question": "整理研究结论，并标记资料范围内无法确认的内容。",
  "dependencies": ["task-2"],
  "allowed_tools": [
    "keyword_search",
    "read_document_range"
  ],
  "max_actions": 4
}
```

Plan Validator 随后检查：

- Task ID 是否唯一；
- 依赖任务是否存在；
- 是否存在循环依赖；
- Source ID 是否超出 SourceManifest；
- Allowed Tools 是否合法；
- Task 数量和动作预算是否超限。

校验通过后，Job 停在：

```text
planning → awaiting_approval
```

### 2.6 用户审批 Plan 与资料快照

用户审批时提交：

```json
{
  "plan_version": 1,
  "manifest_hash": "8a5599e8d44944d6e4d1d563aea17ab79b8a4d18e75287adf3ad1f90b073e0a1"
}
```

系统检查提交值是否与当前 Plan 和 SourceManifest 完全一致，然后生成 Approval Snapshot：

```json
{
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "plan_version": 1,
  "manifest_hash": "8a5599e8d44944d6e4d1d563aea17ab79b8a4d18e75287adf3ad1f90b073e0a1",
  "approved_by": "demo-user",
  "approved_at": "审批时间"
}
```

审批成功后：

```text
awaiting_approval → ready
```

如果用户审批的是旧 Plan Version，或者审批期间资料快照已改变，审批会失败，而不是执行一份用户没有确认过的计划。

### 2.7 Dispatcher 领取任务

Dispatcher 扫描到 `ready` Job 后，原子地将它切换为：

```text
ready → researching
```

随后启动 LangGraph Runtime。Graph State 只保存轻量信息：

```json
{
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "current_stage": "execute_tasks",
  "current_task_id": null,
  "plan_version": 1,
  "attempt": 0,
  "entity_ids": []
}
```

Graph State 不保存完整原文和完整 Evidence，业务数据以 Repository 为准。

### 2.8 Search 只生成 Observation

Worker 按 Plan 的依赖顺序执行 Task 1。

Search 找到候选内容：

```text
project-alpha / line:1-1 / 项目 Alpha 的部署状态为已完成。
project-beta  / line:1-1 / 项目 Beta 的部署状态为已完成。
```

此时系统只保存 Observation，例如：

```json
{
  "observation_id": "observation-...",
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "task_id": "task-1",
  "tool_name": "search",
  "doc_id": "project-alpha",
  "locator_hint": "line:1-1",
  "snippet": "项目 Alpha 的部署状态为已完成。",
  "query": "定位与研究目标直接相关的原始事实"
}
```

Observation 不是 Verified Evidence。原因是搜索摘要可能截断、重排或缺少上下文，不能直接支撑报告中的确定性事实。

### 2.9 Original Read 生成 Verified Evidence

Worker 根据 Observation 中的 `doc_id` 和 `locator_hint` 调用 `read_document_range`，读取真正的原始文档位置。

读取 Alpha 后生成：

```json
{
  "evidence_id": "evidence-046064aed034370e5ae247a9",
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "task_id": "task-1",
  "doc_id": "project-alpha",
  "document_version": "v1",
  "locator": "line:1-1",
  "excerpt": "项目 Alpha 的部署状态为已完成。",
  "content_hash": "与 SourceManifest 一致的完整哈希"
}
```

读取 Beta 后生成同样结构的另一条 Evidence。

Evidence ID 根据 Research、Task、Document、Locator 和 Content Hash 稳定生成。相同任务恢复后再次读取相同位置，不会无限创建重复 Evidence。

这一步形成了明确边界：

```text
Search → Observation
Original Read → Verified Evidence
```

### 2.10 从 Evidence 生成 Finding

成功读取原文后，Worker 才能生成 Finding：

```json
{
  "finding_id": "finding-...",
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "task_id": "task-1",
  "statement": "项目 Alpha 的部署状态为已完成。",
  "evidence_ids": [
    "evidence-046064aed034370e5ae247a9",
    "evidence-25ceac6173990758aa823b7e"
  ],
  "covers": ["criterion-1"]
}
```

Finding 不只是自然语言句子，它同时保留 Evidence 引用和 Acceptance Criterion 映射。

三个 Task 执行完成后，Job 中可以看到：

```text
task_completed = 3
task_total     = 3
evidence_count = 6
```

### 2.11 Coverage 检查

Coverage Engine 将所有 Finding 的 `covers` 与 Plan 中的 Acceptance Criteria 对比。

本例结果：

```json
{
  "covered": [
    "criterion-1",
    "criterion-2"
  ],
  "missing": [],
  "sufficient": true
}
```

Coverage 回答的是：计划要求调查的内容是否都得到了证据支持，而不是只判断程序有没有报错。

### 2.12 生成 Claim Draft

Claim Generator 只根据已经保存的 Finding 生成候选结论，不重新搜索，也不增加 Finding 中不存在的新事实。

示例：

```json
{
  "claim_id": "claim-finding-...",
  "research_id": "research-9683da6aa8ad46558fb1fcce3aee030a",
  "claim_text": "项目 Alpha 的部署状态为已完成。",
  "evidence_ids": [
    "evidence-046064aed034370e5ae247a9"
  ],
  "criterion_ids": ["criterion-1"]
}
```

此时它仍然是 `ClaimDraft`，还不能直接进入最终报告。

### 2.13 Structural Verification

Structural Verifier 对 Claim 进行确定性检查：

1. `evidence-046...` 是否真实存在；
2. Evidence 是否属于当前 `research_id`；
3. `project-alpha` 是否在当前 SourceManifest；
4. Locator 是否为合法的 `line:1-1`；
5. Content Hash 是否与 Manifest 一致。

本例所有检查通过，Claim 才会进入下一阶段。

如果 Claim 引用了其他 Job 的 Evidence，结果会是：

```json
{
  "status": "unsupported",
  "reason": "evidence_belongs_to_another_research_job"
}
```

该 Claim 不会进入 Semantic Verification。

### 2.14 Semantic Verification

Semantic Verifier 判断 Claim 内容是否真正得到 Evidence 支持。

本例中：

```text
Claim：项目 Alpha 的部署状态为已完成。
Evidence：项目 Alpha 的部署状态为已完成。
Result：supported
```

验证结果示意：

```json
{
  "claim_id": "claim-finding-...",
  "status": "supported",
  "evidence_ids": [
    "evidence-046064aed034370e5ae247a9"
  ],
  "reason": "claim_is_supported_by_original_evidence"
}
```

完成语义验证后：

```text
researching → synthesizing
```

### 2.15 生成 Markdown Report

Renderer 只读取已经持久化的 Claim、Verification、Coverage 和 Evidence，不执行新的 Search。

报告中的结论保留 Evidence ID：

```markdown
# 比较 Alpha 与 Beta 的部署状态，并给出原文依据

## 结论

- 项目 Alpha 的部署状态为已完成。[E:evidence-046064...]
- 项目 Beta 的部署状态为已完成。[E:evidence-25ceac...]

## 覆盖情况

- 已覆盖：criterion-1, criterion-2
- 缺失：无

## 局限性

- 暂无已记录局限性。

## 证据索引

- evidence-046064...：project-alpha / line:1-1
- evidence-25ceac...：project-beta / line:1-1
```

用户可以从结论中的 Evidence ID 找到证据索引，再定位到具体文档和行号。

### 2.16 完成状态收口

报告保存成功后，Runtime 执行 Finalize：

```text
synthesizing → completed
```

最终 Job：

```json
{
  "status": "completed",
  "current_stage": "completed",
  "result_status": "complete",
  "task_total": 3,
  "task_completed": 3,
  "evidence_count": 6,
  "failure_stage": null,
  "error_code": null
}
```

本例中：

- 流程正常完成，所以 Execution Status 是 `completed`；
- 必需条件均有覆盖；
- Claim 得到 Evidence 支持；
- 没有未解决冲突；
- 因此 Result Status 是 `complete`。

### 2.17 这个例子最终证明了什么

```text
用户问题
  ↓
明确的本地资料范围
  ↓
可审计的计划与审批快照
  ↓
Search Observation
  ↓
原文读取与 Verified Evidence
  ↓
有 Evidence 引用的 Finding 和 Claim
  ↓
结构验证与语义验证
  ↓
带原文定位的 Markdown Report
```

它证明系统不仅“生成了一篇报告”，还能够说明报告使用了哪些资料、执行了哪些任务、每条事实引用了哪条 Evidence，以及服务重启后应该从哪里恢复。

---

## 3. 完整成功场景的展示效果

### 3.1 演示问题

> 比较项目 Alpha 与 Beta 的部署状态，并给出可追溯依据。

选择的固定本地资料：

- `project-alpha`；
- `project-beta`。

### 3.2 创建任务

```http
POST /api/research/jobs
X-User-ID: alice
Content-Type: application/json

{
  "query": "比较 Alpha 与 Beta 的部署状态",
  "source_scope": {
    "document_ids": ["project-alpha", "project-beta"]
  }
}
```

用户首先看到：

```json
{
  "research_id": "research-api-full",
  "status": "created",
  "result_status": null,
  "task_total": 0,
  "task_completed": 0,
  "evidence_count": 0
}
```

这里的关键效果是：接口立即返回，不需要用户等待整个研究过程结束。

### 3.3 系统生成计划并等待审批

Dispatcher 发现新任务后，系统完成以下工作：

1. 根据用户选择冻结 SourceManifest；
2. 记录每份资料的 `doc_id`、版本和 `content_hash`；
3. 生成 Research Plan；
4. 校验任务数量、依赖关系、工具权限和预算；
5. 将 Job 停在 `awaiting_approval`。

状态变化：

```text
created → planning → awaiting_approval
```

计划中可以看到：

| 内容 | 展示效果 |
| --- | --- |
| Objective | 比较 Alpha 与 Beta 的部署状态 |
| Plan Version | 当前审批的计划版本 |
| Manifest Hash | 当前资料快照的唯一哈希 |
| Tasks | 有顺序、有依赖的研究任务 |
| Allowed Tools | keyword_search、read_document_range |
| Acceptance Criteria | 核心事实、原文位置、资料限制 |
| Budget | 最大任务数、动作数、工具调用数和运行时间 |

未经审批时，Worker 不会执行计划。

### 3.4 用户审批

```http
POST /api/research/jobs/research-api-full/approve
X-User-ID: alice
Content-Type: application/json

{
  "plan_version": 1,
  "manifest_hash": "当前 SourceManifest 的哈希"
}
```

审批不是简单的“同意”按钮，而是绑定：

```text
Research ID
+ Plan Version
+ Manifest Hash
+ Approved By
+ Approved At
```

只有版本和哈希都匹配，Job 才会进入 `ready`。

### 3.5 执行研究任务

审批后，状态依次变化：

```text
ready → researching → synthesizing → completed
```

执行阶段的核心区别是：搜索结果不能直接成为证据。

```text
Search Hit
  ↓
Observation
  ↓
读取原始文档指定位置
  ↓
Verified Evidence
```

一条可信 Evidence 包含：

| 字段 | 示例效果 |
| --- | --- |
| Evidence ID | `evidence-...` |
| Research ID | 当前研究任务 |
| Task ID | 产生证据的任务 |
| Document ID | `project-alpha` |
| Locator | `line:1-1` |
| Excerpt | 项目 Alpha 的部署状态为已完成 |
| Content Hash | 与冻结 Manifest 一致的内容哈希 |

### 3.6 最终报告

最终可以通过以下接口查看报告：

```http
GET /api/research/jobs/research-api-full/report
```

报告效果示意：

```markdown
# 比较 Alpha 与 Beta 的部署状态

## 结论

- 项目 Alpha 的部署状态为已完成。[E:evidence-...]
- 项目 Beta 的部署状态为已完成。[E:evidence-...]

## 覆盖情况

- 已覆盖：核心事实、原文位置
- 缺失：无

## 局限性

- 暂无已记录局限性。

## 证据索引

- evidence-...：project-alpha / line:1-1
- evidence-...：project-beta / line:1-1
```

最终状态：

```text
Execution Status: completed
Result Status: complete
```

`completed` 表示流程正常结束，`complete` 表示证据覆盖和结论质量满足当前要求。

---

## 4. 资料不足时的效果

### 4.1 演示问题

> 根据资料说明收入和利润情况。

固定资料中只有收入，没有利润。

### 4.2 系统行为

系统仍然可以正常完成搜索、原文读取、证据入库和报告生成，因此 Execution Status 不是失败。

但是 Coverage 会发现必需条件“利润”没有证据支持：

```text
Execution Status: completed
Result Status: degraded
```

报告不会编造利润，而会显示：

```markdown
## 覆盖情况

- 已覆盖：收入
- 缺失：利润

## 局限性

- 缺失必需验收条件：利润
```

这个场景展示了系统可以区分“程序执行失败”和“资料质量不足”。

---

## 5. 证据冲突时的效果

固定资料：

```text
文档 A：项目预算为 100 万元。
文档 B：项目预算为 120 万元。
```

两份原文都可以形成合法 Evidence，因此 Structural Verification 通过；但 Semantic Verification 会识别内容冲突。

报告效果：

```markdown
- 证据存在冲突，无法形成确定结论：项目预算信息存在两个不同版本。
  [E:evidence-a] [E:evidence-b]
```

最终状态：

```text
Execution Status: completed
Result Status: degraded
Verification Status: conflicting
```

系统不会任意选择 100 万或 120 万作为确定事实。

---

## 6. 结构验证的拦截效果

Claim 在进入语义验证前，必须通过确定性的 Structural Verification。

系统检查：

- 引用的 Evidence 是否存在；
- Evidence 是否属于当前 Research Job；
- Evidence 是否来自当前 SourceManifest；
- Locator 是否完整；
- Content Hash 是否存在并与 Manifest 一致；
- Claim 中的 Evidence ID 是否有效。

以下情况会被直接拒绝：

```text
引用不存在的 Evidence
跨 Job 引用 Evidence
引用 Manifest 外资料
Evidence 缺少原文位置
文档内容已发生变化
```

未通过结构验证的 Claim 不会进入 Semantic Verification，也不会作为确定性事实进入报告正文。

---

## 7. 进程重启恢复的效果

系统分别验证了多个中断位置。

### 7.1 创建任务后重启

```text
created
  → 进程退出
  → 新进程启动
  → Dispatcher 重新发现任务
  → planning
  → awaiting_approval
```

Research Job 不会因为服务重启丢失。

### 7.2 Manifest 保存后重启

恢复后继续使用同一份冻结资料快照：

```text
恢复前 Manifest Hash = 恢复后 Manifest Hash
```

不会在重启后偷偷扩大或改变研究资料范围。

### 7.3 Evidence 保存后重启

```text
Evidence 已入库
  → 模拟进程退出
  → 从安全 Checkpoint 恢复
  → 重放当前阶段
  → Evidence 稳定 ID 去重
  → 继续生成 Finding 和 Report
```

效果：

```text
恢复前 Evidence 数量 = 恢复后 Evidence 数量
```

已保存证据不会因恢复重复生成。

### 7.4 Report 保存后重启

如果 Report 已经持久化，但 Job 还没有完成最终状态收口，恢复时会复用已有 Report，只补做 Finalize。

### 7.5 没有安全恢复点

如果 Job 显示正在执行，但不存在可信 Checkpoint，系统不会猜测执行位置：

```json
{
  "status": "failed",
  "error_code": "research_checkpoint_missing"
}
```

这样可以避免任务永久停留在 `running` 状态。

---

## 8. 取消任务的效果

用户可以在允许的阶段取消任务：

```http
POST /api/research/jobs/{research_id}/cancel
```

状态变化：

```text
created → cancelled
```

取消之后：

- Dispatcher 不再领取该任务；
- Job 保持终态 `cancelled`；
- 不会生成 Research Report；
- 查询未生成的报告返回 404。

---

## 9. 可重复性的效果

相同的 Research ID、问题、固定资料和确定性 Pipeline 连续运行两次，最终 Markdown 报告完全一致。

为了保证这一点，系统不使用数据库写入时间决定报告内容顺序，而是按照稳定的业务内容和实体 ID 排序。

可以用以下方式展示：

```text
Run 1 Report Hash: 8f...
Run 2 Report Hash: 8f...
Reports Equal: true
```

可重复性意味着固定 Fixture 可以稳定用于回归测试和现场演示。

---

## 10. 持久化结构与运行边界

### 10.1 Repository 保存的权威业务对象

- ResearchJob；
- SourceManifest；
- ResearchPlan；
- Approval Snapshot；
- ResearchTask；
- Observation；
- VerifiedEvidence；
- Finding；
- CoverageResult；
- ClaimDraft；
- VerificationResult；
- ResearchReport；
- WorkflowCheckpoint。

### 10.2 LangGraph Checkpoint 只保存轻量运行状态

```text
research_id
current_stage
current_task_id
plan_version
attempt
entity_ids
```

Checkpoint 不保存原始文档全文，也不保存完整 Evidence。业务数据以 Repository 为准，Graph State 只负责流程推进和恢复定位。

---

## 11. 本周测试结果

### Day 5 纵向切片

```text
11 passed
```

覆盖：

- 手动 API 完整链路；
- Mock Full E2E；
- 固定本地资料 Full E2E；
- 资料不足降级；
- 证据冲突降级；
- 创建后重启；
- Manifest 后重启；
- Evidence 后重启；
- Report 后重启；
- 无安全 Checkpoint 显式失败；
- 基础取消。

### 项目全量回归

```text
364 passed, 3 warnings
```

3 个 warning 均为第三方依赖的弃用提示，没有业务测试失败。

---

## 12. 建议的现场展示顺序

建议用 8～10 分钟完成演示：

1. 创建 Alpha/Beta 对比任务；
2. 展示 SourceManifest、Plan 和 Approval Snapshot；
3. 审批并执行任务；
4. 展示状态从 `ready` 到 `completed`；
5. 打开带 Evidence 引用的 Markdown 报告；
6. 从 Evidence ID 反查 `doc_id / line:x-y`；
7. 展示资料不足的 `degraded` 报告；
8. 展示 Evidence 入库后的重启恢复；
9. 展示取消任务后 Dispatcher 不再执行；
10. 展示 `364 passed` 的全量测试结果。

一句话总结本周效果：

> 用户可以围绕明确的本地资料创建研究任务，在审批资料快照和计划后，让系统持久、可恢复地完成研究，并获得每条事实都能追溯到原文位置的 Markdown 报告；当证据不足或冲突时，系统会明确降级，而不是编造确定结论。
