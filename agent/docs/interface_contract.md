# Web-Agent Interface Contract

## POST `/api/chat`

Request:

```json
{
  "query": "What features are required for project Q1?",
  "session_id": "optional-session-id",
  "top_k": 5,
  "filters": null,
  "stream": false,
  "retrieval_mode": "hybrid"
}
```

Fields:

- `query`: required user query.
- `session_id`: optional conversation identifier.
- `top_k`: number of retrieval results; defaults to `5`.
- `filters`: optional retrieval constraints.
- `stream`: whether streaming output is requested.
- `retrieval_mode`: `vector`, `bm25`, or `hybrid`; defaults to `hybrid`.

## ChatResponse

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "Answer content [1]",
  "message": "",
  "citations": []
}
```

The public response remains limited to these five fields in CP2. Iteration
counts and tool traces stay in Agent logs and internal run summaries until a
separate Web contract revision approves an optional `run` field.

## Citation Fields

- `citation_id`: citation number starting from `1`.
- `title`: document title.
- `source_url`: optional source link.
- `doc_id`: document identifier.
- `chunk_id`: chunk identifier.
- `score`: retrieval score.
- `snippet`: document excerpt, defaulting to the first 120 characters of
  `chunk_text`.

## Status Values

- `success`：成功。
- `clarification_required`：问题存在歧义，`message` 中返回 Agent 的澄清问题。
- `agent_limit_reached`：达到最大迭代数或重复工具调用阈值后安全停止。
- `tool_error`：非检索工具不存在、参数无效或执行失败。
- `invalid_query`：问题为空或无效。
- `no_relevant_context`：知识库没有足够上下文。
- `retrieval_error`：检索服务异常。
- `llm_error`：模型服务异常。

- `success`: request completed successfully.
- `clarification_required`: the query is ambiguous; `message` contains the
  Agent's clarification question.
- `agent_limit_reached`: execution stopped safely after reaching an iteration
  or repeated-call limit.
- `tool_error`: a non-retrieval tool is missing, receives invalid arguments, or
  fails during execution.
- `unsupported`: the request is outside the current capability boundary.
- `invalid_query`: the query is empty or invalid.
- `no_relevant_context`: the knowledge base contains insufficient context.
- `retrieval_error`: the retrieval service failed.
- `llm_error`: the model service failed.

## Error Response

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "invalid_query",
  "answer": "",
  "message": "Please enter a valid question.",
  "citations": []
}
```

## Web Handling

- For `status == success`, display `answer` and `citations`.
- For `status == clarification_required`, display `message` and allow the user
  to reply under the same `session_id`.
- For other non-success statuses, display `message` and do not display the empty
  `answer`.
- Include `trace_id` in logs and issue reports.
- Match citation markers such as `[1]` and `[2]` by `citation_id`.

## CP2 Conversation Rules

- Web must pass the same `session_id` throughout one conversation when
  multi-turn context is enabled.
- An empty `session_id` produces a stateless single-turn request.
- Current memory is short-term, in-process Agent memory and is not shared across
  restarts or multiple workers.
- Agent public response fields remain unchanged. Iteration counts and tool
  traces stay in internal Agent run summaries and logs.
