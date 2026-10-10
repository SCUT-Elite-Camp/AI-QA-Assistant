# CP2 Day 3–4 Research Runtime 交付说明

本交付建立在 `origin/agent-dev@29022eb` 的 Day 1–2 集成控制面之上，统一复用：

- `agent.schemas.research` Contract v2；
- `deep_research.repository.SQLiteResearchRepository`；
- `deep_research.service.ResearchControlPlane`；
- `ApprovedResearchContext` 和已冻结的 `SourceManifest`。

没有引入第二套 Job、Plan、Manifest、Approval 或 Repository。

## Day 3：Research Loop Runtime

### Local Research Tool Adapter

提供：

- `list_documents`；
- 本地 `search`，映射现有 keyword / semantic / hybrid 检索；
- `read_document_range` 原文读取。

每次调用携带 `research_id`、`task_id`、`trace_id`、`user_id`、`SourceManifest` 和 timeout。Adapter 对 Search 结果进行 Manifest 二次过滤；读取时重新检查文档权限和内容哈希，Manifest 外文档、内容版本变化和超时均明确失败。

### Observation / Evidence Ledger

固定边界：

```text
Search Result → Observation
Original Read → VerifiedEvidence
```

Search snippet 不能直接保存为 Evidence。Evidence ID 由 Job、Task、文档、Locator 和内容哈希确定性生成，重试同一位置不会重复写入。

## Day 4：Trustworthy Reporting Runtime

### Repository 扩展

SQLite 新增持久化能力：

- Observation；
- VerifiedEvidence；
- Finding；
- CoverageResult；
- ClaimDraft；
- VerificationResult；
- ResearchReport；
- WorkflowCheckpoint。

Repository 仍是完整业务状态的唯一真相；Checkpoint 只保存阶段、当前 Task、Plan Version、Attempt 和实体 ID。

### Structural Verifier

在 Semantic Verification 前确定性检查：

- Evidence ID 是否存在；
- Evidence 是否属于当前 Job；
- 文档是否属于冻结 Manifest；
- Locator 和 Content Hash 是否完整；
- Claim 是否显式绑定 Evidence。

失败 Claim 保存为结构校验结果，但不会传给 Semantic Verifier。

### LangGraph Runtime

生产 Graph 骨架：

```text
prepare
→ execute_tasks
→ coverage
→ generate_claims
→ structural_verification
→ semantic_verification
→ render_report
→ finalize
```

成员 A 的 Worker、Coverage、Claim Generator、Semantic Verifier 和 Renderer 通过 `IntelligencePipeline` 接口注入；Graph State 只传实体 ID，不保存原文、完整 Evidence 或报告正文。

### Report API

新增：

```text
GET /api/research/jobs/{research_id}/report
```

报告从 Repository 查询，不在 API 层临时生成。

## 验证

Gate 3 / Gate 4 定向测试：`8 passed`。

完整回归：

```text
349 passed, 3 third-party deprecation warnings
```

测试证明：

- Search Hit 直接成为 Evidence 次数为 0；
- Manifest 外结果不会进入 Observation/Evidence；
- Evidence Locator 完整并且重复读取幂等；
- 无效 Claim 被 Structural Verifier 拦截；
- Semantic Verifier 只收到结构合法 Claim；
- Report 和 Checkpoint 可独立从 Repository 查询；
- Graph State 不包含 Evidence excerpt。

## Day 5 边界

Day 5 仍需完成：

- 将成员 A 的真实 Intelligence Pipeline Adapter 接入 Graph；
- SQLite LangGraph Checkpointer 与进程重启恢复测试；
- Mock Full E2E；
- Fixed Local Fixture Full E2E；
- `completed / degraded` 两条结果路径；
- Restart 后 Resume 或 Explicit Fail。
