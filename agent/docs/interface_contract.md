# Web-Agent 接口契约

## POST /api/chat 请求格式

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "optional-session-id",
  "top_k": 5,
  "filters": null,
  "stream": false,
  "retrieval_mode": "hybrid"
}
```

字段说明：

- `query`：用户问题，必填。
- `session_id`：会话 ID，选填。
- `top_k`：检索数量，默认 5。
- `filters`：预留过滤条件，选填。
- `stream`：是否期望流式输出，Q1 仅预留。
- `retrieval_mode`：检索模式，支持 `vector`、`bm25`、`hybrid`，默认 `hybrid`。

## ChatResponse 响应格式

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "答案内容 [1]",
  "message": "",
  "citations": []
}
```

## Citation 字段

- `citation_id`：引用编号，从 1 开始。
- `title`：文档标题。
- `source_url`：来源链接，选填。
- `doc_id`：文档 ID。
- `chunk_id`：分块 ID。
- `score`：检索分数。
- `snippet`：文档片段，默认取 `chunk_text` 前 120 字。

## status 枚举

- `success`：成功。
- `clarification_required`：问题存在歧义，`message` 中返回 Agent 的澄清问题。
- `agent_limit_reached`：达到最大迭代数或重复工具调用阈值后安全停止。
- `tool_error`：非检索工具不存在、参数无效或执行失败。
- `invalid_query`：问题为空或无效。
- `no_relevant_context`：知识库没有足够上下文。
- `retrieval_error`：检索服务异常。
- `llm_error`：模型服务异常。

## 异常响应格式

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "invalid_query",
  "answer": "",
  "message": "请输入有效问题。",
  "citations": []
}
```

## Web 层解析建议

- `status == success` 时展示 `answer` 和 `citations`。
- `status == clarification_required` 时展示 `message`，并允许用户在同一
  `session_id` 下继续回复。
- 其他 `status != success` 时展示 `message`，不要展示空 `answer`。
- 所有日志和问题排查都携带 `trace_id`。
- `citations` 可按 `citation_id` 与答案中的 `[1]`、`[2]` 对应展示。

## CP2 会话约定

- Web 希望启用多轮上下文时，应在同一段对话中稳定传入同一个 `session_id`。
- `session_id` 为空时按无记忆单轮请求处理。
- 当前记忆为 Agent 进程内短期记忆，服务重启或多 worker 不保证共享。
- Agent 对外响应字段保持不变；迭代次数和工具轨迹仅保留在 Agent 运行摘要及日志中。
