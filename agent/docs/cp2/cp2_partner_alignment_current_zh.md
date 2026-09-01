# CP2 Agent 当前版本搭档对齐说明

> 更新时间：2026-08-09
> 用途：与 Memory、工具层、Web/API 和主流程搭档同步当前 Agent 状态与待协作事项。

## 1. 一句话状态

Agent 已完成从 Query Understanding 到证据门禁、纠正检索、分层答案生成和引用检查的有界链路；当前最需要搭档协助的是工具层正式契约文档的召回排序，以及团队环境中的模型配置确认。

## 2. 公共契约状态

以下公共契约继续保持冻结，本轮性能和评测优化没有修改其字段：

- `QueryPlan` 公共契约；
- `ConversationMemory` 公共契约；
- Web-Agent `ChatRequest` / `ChatResponse` 接口契约；
- ToolRegistry / ToolExecutor 已约定接口。

`multi_aspect_scope` 是 Agent 内部派生的复杂度信号，不写入 QueryPlan，因此不会要求搭档同步修改公共模型。

## 3. Agent 当前输入与输出边界

### QueryPlan 输入

Agent 直接消费：

- `original_query`
- `standalone_query`
- `intent`
- `intent_confidence`
- `is_follow_up`
- `is_clarification_reply`
- `needs_clarification`
- `clarification_question`
- `ambiguity_reason`
- `sub_queries`
- `filters`

### 工具调用输入

通过 ToolRegistryAdapter 获取 Schema 后，ToolExecutor 使用：

- `tool_call_id`
- `tool_name`
- `arguments`
- `trace_id`
- `retrieval_attempt`

`search_documents` 仍接收 `standalone_query`、`top_k`、`mode`、硬过滤条件和 trace ID。

### 工具返回 Evidence 最低要求

- `doc_id`
- `chunk_id`
- `title`
- 内容字段
- `score`
- 推荐同时返回 `source_url`、`retrieval_query` 和 `retrieval_mode`

### Web/API 输出

公共响应继续保持：

- `trace_id`
- `status`
- `answer`
- `message`
- `citations`

前端不能只根据 HTTP 200 判断成功，必须结合业务 `status`。

## 4. 当前 Agent 流程

```text
ConversationMemory
  → Hybrid Intent Router（规则 / BGE / LLM 回退）
  → Query Preparation
  → QueryPlan
  → IntentPolicy
  → ToolRegistryAdapter
  → ToolExecutor
  → Evidence Gate
  → 最多一次 Corrective Retrieval
  → 快慢答案模型路由
  → Answer Completeness
  → Citation Check
  → Memory 写回
  → ChatResponse
```

comparison 可以基于 `sub_queries` 并行调用检索工具，工具实现需要能够安全处理同一请求内的并发调用。

## 5. 当前模型分工

这是本地实验配置，不代表团队默认值：

| 环节 | 当前本地模型/方法 |
|---|---|
| 明确意图识别 | 高精度规则 + 本地 BGE |
| 边界意图识别 | qwen3.7-plus-2026-05-26 回退 |
| Query Preparation | qwen3.6-flash |
| 单目标答案 | qwen-flash |
| 复杂/多环节答案 | qwen3.7-plus-2026-05-26 |
| 单目标完整性 | 本地引用检查 |
| 复杂答案完整性 | qwen3.6-flash |

任何个人 API Key、`.env` 和个人免费额度模型配置都不会提交。

## 6. 已完成并需要搭档知晓的改进

- Query Understanding 已由多次串行调用改为级联结构；
- BGE 已配置本地路径、缓存和服务启动预热；
- `/ready` 包含 `intent_ready`；
- Query Preparation 支持子问题和过滤条件；
- comparison 支持并行分目标检索；
- Evidence Gate 提供覆盖与缺失目标诊断；
- Corrective Retrieval 最多执行一次；
- Evidence 接受后使用干净上下文生成答案，防止重复工具调用；
- 答案生成支持 Flash/Plus 分层和失败回退；
- Answer Completeness 对简单与复杂任务分层；
- 要点评测支持别名、标识符规范化和命中原因记录；
- 当前相关本地回归为 255 项全部通过。

## 7. 需要工具层搭档处理的事项

### 已确认问题

`API_CONTRACT` 已存在于本地文档索引：

- title：`API_CONTRACT`
- doc_id：`1930cc53d9190e14c0d20e3f7981318a`
- source：`agent/docs/API_CONTRACT.md`

但查询“CP2 API 问答请求从进入系统到返回答案的核心步骤”时，hybrid top 10 中没有该文档，结果主要是：

- `cp1_cp2_architecture_overview`
- Q2 reporting 会议记录
- MVP refinement 会议记录

### 希望工具层确认

1. BM25、向量检索和融合候选中，`API_CONTRACT` 分别排在什么位置；
2. 英文契约内容与中文查询是否造成跨语言向量召回不足；
3. 是否应对标题、文件名或 repository path 的明确匹配加权；
4. 正式契约文档是否应优先于会议记录；
5. 是否增加 `doc_type=contract`、`source_type=repository_markdown` 等元数据；
6. reranker 是否已实际启用；
7. top_k 之前的 candidate pool 是否过小。

### 建议但不强制的检索策略

```text
用户查询
  → 标题/文件名精确或模糊匹配
  → BM25 + Vector 候选
  → 文档类型与来源可信度加权
  → 去重
  → rerank
  → top_k
```

Agent 负责调用控制、Evidence 消费和纠正检索；召回率、候选融合和排序仍由工具层负责。

## 8. 需要 Memory 搭档确认的事项

- pending clarification 的写入、读取、消费和清除语义；
- `session_id` 的隔离边界；
- 多 Worker 或多实例是否采用 Redis；
- 摘要触发条件、历史窗口和截断规则；
- Redis 不可用时是否允许降级为进程内存；
- 当前 QueryPlan 仍通过读取历史消息完成指代解析，Memory 不需要理解意图。

## 9. 需要 Web/API 搭档确认的事项

- `ChatResponse` 是否正式包含 `chat_title`；
- `clarification_required` 时使用 `message` 展示澄清问题；
- 正确处理 `no_relevant_context`、`tool_error`、`agent_limit_reached` 和 `llm_error`；
- citations 的编号、`doc_id`、`chunk_id` 和来源显示是否保持一致；
- 前端超时是否覆盖复杂问题约 50–90 秒的当前实验范围；
- 流式输出尚不是当前冻结主契约的一部分。

## 10. 最新在线验证数据

两条多环节知识问题最新回归：

| 指标 | 结果 |
|---|---:|
| 成功回答率 | 100% |
| 意图准确率 | 100% |
| 引用有效率 | 100% |
| 重复工具调用率 | 0% |
| Policy Limit 发生率 | 0% |
| 预期文档命中率 | 50% |
| 平均端到端耗时 | 52.95 秒 |

API 流程题未命中 `API_CONTRACT`，因此不能用继续更换答案模型来解决，必须先改善检索证据入口。

## 11. 合并与提交提醒

- 当前工作位于本地开发分支，提交前必须审查全部 diff；
- 不提交 `.env`、API Key、模型权重、数据库运行文件和临时报告；
- `ANSWER_FAST_MODEL=qwen-flash` 目前属于个人环境实验配置，不应直接成为团队默认值；
- 公共契约未变，但新增的评测字段和内部复杂度逻辑需要在 PR 描述中说明；
- 工具层召回问题建议由工具层单独提交修复，并使用同一测试问题进行回归。

## 12. 建议发给搭档的简短消息

> Agent 当前已完成级联 Query Understanding、BGE 混合意图、复合问题拆分与并行检索、Evidence Gate、最多一次纠正检索、快慢答案模型路由、Answer Completeness 和 Citation Check。QueryPlan、ConversationMemory、Web-Agent 与 ToolRegistry 公共契约没有变化。最新测试发现 `API_CONTRACT` 已在索引中，但中文 API 流程查询的 hybrid top 10 未召回它，会议记录和架构总览占据候选。请工具层帮忙检查标题/路径加权、跨语言召回、candidate pool、文档类型优先级和 reranker；Agent 侧会继续负责有界调用、证据门禁和引用检查。
