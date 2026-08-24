# CP2 Research Contract v1

## 范围

这是手动启动 Local Research 的第一版契约。Week 1 只冻结数据结构、确定性 Plan Validator 和 Mock Fixture，不实现 Job 创建、Planner LLM 调用、Worker 或报告执行。

唯一版本号是 `research.v1`。所有契约使用 Pydantic `extra="forbid"`，未知字段直接拒绝，避免 A/B 两侧静默漂移。

实现位置：

```text
agent/agent/schemas/research.py
agent/mock/research_contract_fixtures.json
```

## 主要对象

### ResearchRequest

用户提交的研究目标、显式本地来源范围、报告要求和标准 Profile。客户端不能提交发起人身份；身份上下文由后续服务端入口补充。

### SourceScope

至少指定一个本地知识库 ID、文档 ID 或主题。`http://`、`https://`、`www.` 和带协议的外部来源会被拒绝。CP2 不允许来源为空后自动扩展。

### ReportSpec

CP2 v1 只输出 Markdown，默认中文，保留引用和限制性说明。Plan Validator 会拒绝关闭引用的报告计划。

### ResearchPlan / ResearchTask

Planner 输出版本化研究计划。任务包含问题、目的、依赖、允许的 Local 只读工具、可选来源 ID、验收条件、优先级和动作预算。

### ResearchBudget

硬预算包括最大任务数、动作数、工具调用数、Token 数和运行时间。预算由服务端策略控制，未来不能由模型自行扩大。

## Local Tool Allowlist

```text
list_documents
get_document_outline
keyword_search
semantic_search
read_document_range
```

Week 1 契约中没有网络搜索、网页读取、写文件、代码执行或任意 SQL 工具。

## Plan Validator 稳定错误码

| 错误码 | 含义 |
|---|---|
| `research_plan_empty_tasks` | 任务列表为空 |
| `research_plan_duplicate_task_id` | Task ID 重复 |
| `research_plan_duplicate_task_question` | 任务问题高度重复 |
| `research_plan_unknown_dependency` | 依赖的 Task 不存在 |
| `research_plan_dependency_cycle` | 依赖关系成环 |
| `research_task_tool_not_allowed` | 使用了 Local allowlist 外的工具 |
| `research_task_source_out_of_scope` | 任务来源超出 ResearchRequest/Plan 范围 |
| `research_task_acceptance_criteria_missing` | 任务没有验收条件 |
| `research_plan_task_budget_exceeded` | 任务数超过预算 |
| `research_plan_action_budget_exceeded` | 动作数超过预算 |
| `research_report_citations_required` | 报告关闭了引用 |
| `research_source_scope_required` | 没有显式来源范围 |

`ResearchPlanValidator.validate_or_raise()` 对同一输入始终先返回同一条错误码，测试不依赖真实 LLM。

## Fixture

`research_contract_fixtures.json` 包含：

- 一个 ResearchRequest；
- 至少三个合法计划：单事实、比较、主题总结；
- 空任务、重复 ID、重复问题、依赖环、非法工具、越权来源、超预算、缺少验收条件等非法计划。

后续 Planner 和 Runtime 必须先通过这些契约测试，再接入真实组件。

