# Agent Layer Q1 需求文档

## 文档状态

- 项目名称：Agent Layer
- 版本：Q1 v1.1
- 状态：明确
- 更新日期：2026-06-29

本文档以 `agent-dev` 当前实现为准，覆盖 Week 1 到 Week 3 已完成能力，并作为 Week 4 Web 联调的验收依据。

## REQ-CHAT-001 智能问答接口

### 需求描述

系统提供统一智能问答接口，接收用户问题，完成参数校验、检索、Prompt 构建、LLM 调用、答案格式化，并返回标准 JSON 响应。

### 关联接口

`POST /api/chat`

### 权限

Q1 不做登录鉴权。

### 输入字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 用户问题，去除空白后不能为空。 |
| `session_id` | string | 否 | 会话 ID，Q1 预留。 |
| `top_k` | int | 否 | 检索数量，默认 `5`，范围 `1-20`。 |
| `retrieval_mode` | string | 否 | 检索模式，支持 `vector`、`bm25`、`hybrid`。 |
| `filters` | object | 否 | 检索过滤条件，预留 `doc_id`、`space`、`doc_type` 等。 |
| `stream` | bool | 否 | 是否流式，Q1 仅预留，当前仍返回普通 JSON。 |

### 输出字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trace_id` | string | 请求唯一标识。 |
| `status` | string | 请求状态。 |
| `answer` | string | 回答内容。异常时为空。 |
| `message` | string | 异常或提示信息。成功时为空。 |
| `citations` | array | 引用列表。异常时为空。 |

### 状态码

| 场景 | 状态 |
| --- | --- |
| 正常回答 | `success` |
| `query` 为空 | `invalid_query` |
| 检索为空或低相关 | `no_relevant_context` |
| Tool Layer / Retrieval Adapter 异常 | `retrieval_error` |
| LLM 异常或空输出 | `llm_error` |

### 验收标准

- `POST /api/chat` 能返回标准 JSON。
- 正常问题返回 `success`、`answer` 和 `citations`。
- 空问题返回 `invalid_query`，且不调用检索和 LLM。
- 检索为空返回 `no_relevant_context`。
- 检索结果低于 `MIN_RETRIEVAL_SCORE` 时返回 `no_relevant_context`。
- Tool Layer 异常返回 `retrieval_error`。
- LLM 异常或空输出返回 `llm_error`。

## REQ-RET-001 Retrieval Adapter

### 需求描述

Retrieval Adapter 负责统一 Agent Layer 与 Tool Layer 的检索接口，屏蔽 Mock 与 Real 检索差异。

### 输入字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 用户问题。 |
| `top_k` | int | 否 | 返回数量，范围 `1-20`。 |
| `mode` | string | 否 | `vector`、`bm25`、`hybrid`。 |
| `filters` | dict | 否 | 检索过滤条件。 |
| `min_score` | float | 否 | 最低相关度阈值，范围 `0.0-1.0`。 |
| `trace_id` | string | 否 | 链路追踪 ID。 |

### 输出

`list[RetrievalResult]`

### 验收标准

- 支持 Mock / Real 两种模式。
- Real 模式自动调用 `SearchTool.search()`。
- 自动转换 Tool Layer 返回结果为 `RetrievalResult`。
- 参数非法、Tool Layer 初始化失败或调用失败时统一抛出 `RetrievalError`。
- 检索阶段日志包含开始、结束和异常记录。

## REQ-RET-002 Tool Layer CP1 接口兼容

### 需求描述

Agent Layer 必须兼容 Tool Layer CP1 `SearchTool` 接口。

### 调用接口

```python
search(
    query,
    top_k,
    mode,
    filters,
    min_score,
    trace_id,
)
```

### 返回字段

- `doc_id`
- `chunk_id`
- `chunk_index`
- `chunk_text`
- `title`
- `score`
- `source_url`

### 验收标准

- `tool_layer.SearchTool` 可以正常 import。
- `SearchTool.search()` 可以正常调用。
- `RetrievalAdapter` 能完成字段映射。
- Real Retrieval Smoke Test 通过。

## REQ-QA-001 可信回答与幻觉抑制

### 需求描述

Agent 必须只基于检索上下文回答；当上下文不足时，不得使用常识补全或编造答案。

### 验收标准

- Prompt 明确要求只基于检索上下文回答。
- Prompt 禁止编造事实、数字、流程、负责人或时间。
- 检索为空或低相关时不调用 LLM。
- LLM 空输出返回 `llm_error`。
- 成功回答中的关键结论应带 citation 编号。

## REQ-CIT-001 引用生成与一致性

### 需求描述

系统根据 `RetrievalResult` 自动生成 `citations`，并保证 answer 中的引用编号能对应到真实 citation。

### Citation 字段

- `citation_id`
- `title`
- `source_url`
- `doc_id`
- `chunk_id`
- `score`
- `snippet`

### 验收标准

- 每条检索结果均生成 citation。
- `snippet` 来源于 `chunk_text`。
- `citation_id` 从 `1` 开始。
- answer 缺少引用编号时，成功响应会补齐 `[1]`。
- answer 包含不存在的引用编号时，会移除无效编号并补齐有效编号。

## REQ-LOG-001 Trace 日志链路

### 需求描述

系统所有请求均生成唯一 `trace_id`，并贯穿 Agent 主流程和检索流程。

### 日志字段

- `trace_id`
- `stage`
- `query`
- `retrieval_mode`
- `top_k`
- `retrieval_count`
- `status`
- `error`

### Retrieval Adapter 日志

- `[RETRIEVAL_START]`
- `[RETRIEVAL_END]`
- `[RETRIEVAL_ERROR]`

### 验收标准

- 每次请求生成唯一 `trace_id`。
- Agent 日志包含 `trace_id` 和阶段信息。
- Retrieval 日志包含 `trace_id`、`mode`、`top_k`、结果数和耗时。
- 检索异常日志包含 `trace_id` 和错误信息。

## REQ-TEST-001 自动化测试

### 需求描述

Agent Layer 提供单元测试与集成测试，覆盖主流程、异常状态、检索适配、日志和引用一致性。

### 覆盖范围

- `success`
- `invalid_query`
- `no_relevant_context`
- `retrieval_error`
- `llm_error`
- Retrieval Adapter
- Tool Layer Smoke Test
- Logger
- Trace
- Answer Formatter
- 低相关过滤
- LLM 空输出
- citation 一致性
- trace-aware retrieval logging

### 当前结果

```text
34 passed
```

## 待确认

1. Tool Layer 正式版本替换当前 smoke stub 的时间。
2. Real LLM 使用哪一个 provider 和模型。
3. Stream 输出是否放入 Q2。
4. Web 前端最终是否需要展示 `trace_id` 和完整 citation metadata。
