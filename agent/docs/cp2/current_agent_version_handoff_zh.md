# CP2 Agent 当前版本交接说明

更新日期：2026-08-09
开发分支：`agent-dev-infra`

## 1. 文档用途

本文用于向 Agent 层、工具层、Web-Agent 接口和会话记忆模块的协作成员说明当前本地版本的真实状态。文档将稳定功能、实验候选和本地个人配置分开描述，避免把尚未合并的测试代码或个人 API 配置视为团队默认行为。

## 2. 当前版本目标

当前 CP2 Agent 已从固定单轮 RAG 流程升级为受 QueryPlan、IntentPolicy 和 Evidence 约束的有界 Agent 流程，重点解决：

- 多轮问题理解与澄清；
- 七类意图识别及确定性策略路由；
- 工具发现、参数校验和调用预算；
- 证据过滤、去重、覆盖检查和定向纠正检索；
- 复合比较任务拆分和并行检索；
- 重复工具调用与答案阶段错误工具调用防护；
- 答案完整性检查、引用检查和分阶段性能观测；
- 不同阶段使用不同模型的可配置路由。

## 3. 当前完整链路

```text
用户请求
  ↓
Conversation Memory
读取历史消息、摘要和待澄清状态
  ↓
Hybrid Intent Router
  ├─ 高精度规则
  ├─ 本地 BGE 原型分类
  └─ 低置信度或有历史时回退 LLM
  ↓
Clarification Gate
  ├─ 明确问题：跳过 LLM 澄清
  └─ 存在真实歧义：调用 Clarifier
  ↓
Query Preparation
一次调用完成指代消解、查询重写、filters 和 sub_queries
  ↓
冻结的 QueryPlan
  ↓
IntentPolicyRouter
  ↓
ToolRegistryAdapter
读取工具层工具及 JSON Schema
  ↓
ToolExecutor
校验工具、参数、超时和结构化结果
  ↓
检索执行
  ├─ 普通问题：standalone_query 单次检索
  └─ comparison：最多 4 个 sub_queries 并行检索
  ↓
Evidence 标准化
  ↓
Evidence Gate
过滤、去重并检查意图专属证据覆盖
  ↓
证据不足？
  ├─ 是：最多一次定向 Corrective Retrieval
  └─ 否：进入答案生成
  ↓
Answer Model Routing
  ├─ 复杂任务：主模型
  └─ 普通单目标：可选快速模型，失败回退主模型
  ↓
答案阶段工具调用防护
  ↓
Answer Completeness Check
  ↓
Citation Check
  ↓
Conversation Memory + Audit + LLM Metrics
  ↓
ChatResponse
```

## 4. 七类意图与策略

| 意图 | 当前策略 |
|---|---|
| `knowledge_qa` | Hybrid 检索；至少一条有效证据；生成事实型回答 |
| `document_search` | 偏向 BM25 和文档身份；返回文档列表 |
| `summarization` | 扩大主题覆盖；使用结构化摘要；复杂答案模型 |
| `comparison` | 拆分比较目标；并行检索；要求全部目标有证据；复杂答案模型 |
| `casual_chat` | 不检索，直接对话 |
| `system_help` | 不查询知识库，说明系统能力 |
| `unsupported` | 策略层停止，不执行工具 |

## 5. 冻结公共契约

### 5.1 QueryPlan

当前实现未修改已冻结的 QueryPlan 公共字段：

```text
original_query
standalone_query
intent
intent_confidence
is_follow_up
is_clarification_reply
needs_clarification
clarification_question
ambiguity_reason
sub_queries
filters
```

复合任务直接复用 `sub_queries`，没有增加第二套任务分解契约。

### 5.2 ConversationMemory

Agent 继续通过会话契约消费：

- `session_id`；
- 历史 `messages`；
- 会话 `summary`；
- pending clarification 状态；
- 多轮追问相关状态。

当前默认记忆实现仍需由团队确认生产环境是否切换到 Redis 或其他共享存储。

### 5.3 工具层接口

工具层继续拥有真实工具和注册表。Agent 只通过 `ToolRegistryAdapter` 消费：

- 工具名称；
- 工具描述；
- 参数 JSON Schema；
- 工具实例；
- 标准化执行结果。

当前 Agent 使用的核心检索工具仍是 `search_documents`。复合任务不是新增多个同义工具，而是对同一个检索工具执行多个独立查询。

## 6. 关键实现变化

### 6.1 Query Understanding

- 新增规则 + BGE + LLM fallback 的混合意图路由；
- 新增 Clarification Gate，减少明确问题的澄清调用；
- 新增 Query Preparation，将重写、指代消解、filters 和 sub_queries 合并为一次调用；
- 保留旧串行链路和 Unified 实验链路，默认不开启；
- 所有结果仍输出冻结的 QueryPlan。

### 6.2 复合任务执行

- `comparison` 且有至少两个 `sub_queries` 时，首轮并行检索；
- 最多执行 4 个去重后的子查询；
- 多个子检索属于同一个 retrieval attempt；
- 每条 Evidence 保留自己的 `retrieval_query`；
- 单侧失败时保留成功侧证据；
- Evidence Gate 只标记缺失目标；
- Corrective Retrieval 只补缺失目标。

### 6.3 工具调用安全边界

- ToolExecutor 继续负责工具存在性、Schema、参数和超时校验；
- IntentPolicy 限制候选工具、工具次数、检索次数和最大迭代；
- 一个检索批次通过 Evidence Gate 后，不再执行同一模型响应中的剩余检索；
- Evidence 已充分后，即使模型再次返回工具结构，也不会继续执行工具；
- 模型无法正常生成正文时，使用不包含工具调用历史的干净 Evidence 上下文生成答案。

### 6.4 Evidence 与答案质量

- Evidence Gate 为确定性逻辑，不调用 LLM；
- 按分数过滤，并按 `doc_id + chunk_id` 去重；
- 根据 intent 检查单事实、文档身份、主题覆盖或多目标覆盖；
- 增加 Answer Completeness，检查子问题和关键方面是否被回答；
- Citation Check 验证引用编号、证据身份和连续性。

## 7. 当前模型分工

代码支持以下阶段模型配置：

```env
LLM_MODEL=<主模型>
QUERY_PREPARATION_MODEL=<Preparation 快速模型，可为空>
ANSWER_FAST_MODEL=<普通答案快速模型，可为空>
ANSWER_FAST_MODEL_THINKING=false
```

当前本地已验证：

```text
Query Preparation：qwen3.6-flash
复杂答案生成：qwen3.7-plus
Answer Completeness：qwen3.7-plus
普通答案候选：qwen-flash，尚未正式启用
```

重要说明：

- `QUERY_PREPARATION_MODEL` 为空时复用主模型；
- Preparation 模型请求失败、JSON 非法或 Schema 非法时回退主模型；
- `ANSWER_FAST_MODEL` 为空时所有答案复用主模型；
- 快速答案模型失败时回退主模型；
- comparison、summarization、多子问题或发生纠正检索时继续使用复杂答案模型；
- API Key 和个人模型选择只存在于本地被 Git 忽略的 `.env`，不得提交。

## 8. 测试结果摘要

### 8.1 混合意图路由

14 条本地问题：

| 指标 | 结果 |
|---|---:|
| 本地规则/BGE覆盖率 | 57.1% |
| 本地覆盖部分准确率 | 100% |
| BGE热启动平均耗时 | 约 10.94 ms |
| BGE P95 | 约 30.46 ms |

### 8.2 级联 Query Understanding

| 指标 | 结果 |
|---|---:|
| 意图准确率 | 100% |
| 澄清准确率 | 100% |
| 查询改写达标率 | 100% |
| 平均耗时 | 约 22.55 秒 |
| P95 | 约 45.87 秒 |

### 8.3 五条复合任务最终有效结果

| 指标 | 结果 |
|---|---:|
| 成功回答 | 5/5 |
| 证据目标完整覆盖 | 5/5 |
| 引用有效 | 5/5 |
| 完整性检查通过 | 5/5 |
| 重复工具调用 | 0 |
| Policy Limit | 0 |
| 平均端到端耗时 | 约 94.97 秒 |

### 8.4 Query Preparation 小模型 A/B

| 指标 | qwen3.7-plus | qwen3.6-flash |
|---|---:|---:|
| 复合规划准确率 | 100% | 100% |
| 回退率 | — | 0% |
| 平均耗时 | 25.96 秒 | 20.29 秒 |
| P95 | 35.10 秒 | 24.36 秒 |

使用 qwen3.6-flash 后，复合任务端到端平均耗时约 88.29 秒，较有效 Plus 基线降低约 7%。

### 8.5 qwen-flash 普通答案候选

8 条普通知识库问题整体结果：

| 指标 | 结果 |
|---|---:|
| 成功回答 | 8/8 |
| 引用有效 | 8/8 |
| 严格答案要点达标率 | 50% |
| 重复工具调用 | 0% |
| Policy Limit | 0% |
| 平均端到端耗时 | 71.92 秒 |

其中只有 3 条真正路由到 qwen-flash，另外 5 条因包含多个 `sub_queries` 继续使用主模型。Flash 的答案生成阶段平均约 7.48 秒，但 3 条中只有 1 条满足当前严格关键词要点阈值。因此 qwen-flash 仍是实验候选，不能据此作为团队默认答案模型。

## 9. 已知问题与风险

1. 端到端延迟仍高，主要耗时来自最终答案生成和 Answer Completeness；
2. Answer Completeness 的 LLM 判断与离线关键词标准存在不一致；
3. 当前普通问题测试集中部分问题实际是多子问题，不能作为纯 Flash 样本；
4. 本地知识库存在会议纪要等噪声文档，个别问题未命中预期文档；
5. Conversation Memory 的共享存储和多 Worker 一致性尚未完全落地；
6. Web 旧契约测试仍有 `chat_title` 字段差异，需要接口负责人确认契约版本；
7. 当前工作区包含尚未提交的实现、测试和报告，不应在未审查 diff 前直接整体提交；
8. 不得提交本地 `.env`、API Key、数据库运行数据或模型文件。

## 10. 建议搭档重点对齐的事项

### Memory 搭档

- 确认 pending clarification 的写入、读取和清除语义；
- 确认 `session_id` 隔离；
- 确认多 Worker 环境下是否使用 Redis；
- 确认摘要触发条件和历史消息裁剪规则。

### 工具层搭档

- 保证 `search_documents` Schema 稳定；
- 结果必须提供 `doc_id`、`chunk_id`、`title`、内容、`score`；
- filters 必须按 QueryPlan 硬约束处理；
- Agent 的并行子查询可能同时调用同一个搜索工具，需要确认检索实现的线程安全性；
- 工具层负责召回率、排序和索引质量，Agent 负责调用控制与证据消费。

### Web/API 搭档

- 确认 `ChatResponse` 是否正式包含 `chat_title`；
- 保持 `status`、`answer`、`message`、`citations`、`trace_id` 字段兼容；
- 前端需要正确显示 `clarification_required`、`no_relevant_context`、`tool_error` 和 `agent_limit_reached`；
- 不应把 HTTP 200 直接视为回答成功，需要结合业务状态。

## 11. 当前建议的合并边界

建议优先审查并合并：

- Query Understanding 级联方案；
- Hybrid Intent Router；
- Clarification Gate；
- Query Preparation 及回退；
- Evidence Gate 诊断；
- 并行 comparison retrieval；
- 重复工具调用和答案阶段工具调用防护；
- 评测框架和数据集结构测试。

建议暂不作为团队默认启用：

- `ANSWER_FAST_MODEL=qwen-flash`；
- 依赖个人百炼账号的模型名称和 API 配置；
- 未与离线标准对齐的 Answer Completeness 优化策略。

## 12. 交接时需要明确说明

- QueryPlan、ConversationMemory 和工具层公共契约没有被本次性能实验随意修改；
- qwen3.6-flash 已证明适合 Query Preparation，但是否作为团队默认值应由团队环境决定；
- qwen-flash 普通答案路由只有代码和初步测试，不应宣称已经正式上线；
- 当前最主要的下一步是优化 Answer Completeness，并建立纯单目标普通问题的同题 Plus/Flash A/B；
- 当前改动仍位于本地 `agent-dev-infra`，尚未提交或上传。
