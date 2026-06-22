# 测试用例

## 正常问答

- 输入有效 `query`。
- Mock Retrieval 返回 3 条文档块。
- Mock LLM 返回答案。
- 期望 `status = success`，包含 `answer`、`trace_id`、`citations`。

## 空输入

- 输入空字符串或纯空格。
- 不调用 retrieval 和 LLM。
- 期望 `status = invalid_query`。

## 无相关文档

- Mock Retrieval 返回空列表。
- 不调用 LLM。
- 期望 `status = no_relevant_context`。

## 检索异常

- Mock Retrieval 抛异常。
- 期望 `status = retrieval_error`。

## LLM 异常

- Mock LLM 抛异常。
- 期望 `status = llm_error`。

## citations 生成

- 输入 RetrievalResult 列表。
- 期望 Citation 从 1 编号，并包含 `doc_id`、`chunk_id`、`title`、`source_url`、`score`、`snippet`。

## 真实 Tool Layer 冒烟

- 设置 `USE_MOCK_RETRIEVAL=false`。
- 通过 `tool_layer.SearchTool.search()` 获取检索结果。
- 期望 Agent 返回 `status = success`，并包含 Tool Layer 结果生成的 citations。
- Tool Layer 不可导入或检索异常时，期望 Agent 返回 `status = retrieval_error`，服务不崩溃。

## trace_id 追踪

- 每次请求生成 `trace-xxxxxxxx` 格式 ID。
- 日志记录 `trace_id`、`query`、`retrieval_count`、`status`。
