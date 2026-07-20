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
- `status != success` 时展示 `message`，不要展示空 `answer`。
- 所有日志和问题排查都携带 `trace_id`。
- `citations` 可按 `citation_id` 与答案中的 `[1]`、`[2]` 对应展示。
