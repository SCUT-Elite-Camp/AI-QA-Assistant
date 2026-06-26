# Q1 Web 接口契约

本文档定义 Vue 前端、Java Spring Boot BFF 和 Agent 层之间的 Q1 接口契约。开发时优先保持本文件稳定。

## 1. Vue 调用 BFF

### 1.1 问答接口

```text
POST /api/v1/chat
```

请求头：

```text
Content-Type: application/json
Accept: application/json 或 text/event-stream
```

请求体：

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "stream": true
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| query | string | 是 | 用户问题，空字符串和纯空格不允许发送 |
| session_id | string | 否 | 当前会话 ID，缺失时 BFF 可生成 |
| stream | boolean | 否 | 是否请求流式输出，默认 `true` |

### 1.2 普通 JSON 响应

```json
{
  "trace_id": "trace-001",
  "status": "success",
  "answer": "Q1 阶段需要打通用户提问、检索、生成答案和展示引用的基础链路。",
  "citations": [
    {
      "index": 1,
      "title": "Q1 范围说明",
      "doc_id": "doc-q1-scope",
      "chunk_id": "chunk-001",
      "source_url": "/documents/doc-q1-scope"
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| trace_id | string | 是 | 请求追踪 ID |
| status | string | 是 | 业务状态 |
| answer | string | 是 | 答案正文或错误提示 |
| citations | array | 是 | 引用来源，没有引用时返回空数组 |

### 1.3 Citation 结构

```json
{
  "index": 1,
  "title": "Q1 范围说明",
  "doc_id": "doc-q1-scope",
  "chunk_id": "chunk-001",
  "source_url": "/documents/doc-q1-scope"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| index | number | 是 | 引用编号，从 1 开始 |
| title | string | 是 | 文档标题 |
| doc_id | string | 是 | 文档 ID |
| chunk_id | string | 是 | 文档分块 ID |
| source_url | string | 否 | 来源链接；为空时页面展示本地文档信息，不生成链接 |

## 2. SSE 响应协议

当 `stream=true` 且后端支持流式输出时，BFF 返回 `text/event-stream`。

### 2.1 meta 事件

```text
data: {"type":"meta","trace_id":"trace-001","status":"generating"}
```

用途：

- 告诉前端本次请求的 `trace_id`；
- 告诉前端进入生成状态。

### 2.2 token 事件

```text
data: {"type":"token","token":"Q1 阶段"}
```

用途：

- 前端将 `token` 增量追加到助手消息中；
- 用户不应看到原始 `data:` 内容。

### 2.3 done 事件

```text
data: {"type":"done","trace_id":"trace-001","status":"success","citations":[{"index":1,"title":"Q1 范围说明","doc_id":"doc-q1-scope","chunk_id":"chunk-001","source_url":"/documents/doc-q1-scope"}]}
```

用途：

- 结束 loading；
- 更新最终状态；
- 展示 citations。

### 2.4 error 事件

```text
data: {"type":"error","trace_id":"trace-001","status":"stream_error","message":"生成中断，请稍后重试"}
```

用途：

- 前端结束 loading；
- 展示对应错误提示；
- 保留 `trace_id`。

### 2.5 结束标志

```text
data: [DONE]
```

前端收到后关闭流式读取。

## 3. 状态枚举

| status | 页面提示 |
|---|---|
| success | 正常展示答案 |
| empty_input | 请输入问题 |
| no_relevant_context | 当前知识库没有足够信息回答该问题 |
| retrieval_error | 检索服务暂时不可用，请稍后重试 |
| llm_error | 模型服务暂时不可用，请稍后重试 |
| network_error | 网络连接异常，请检查服务是否启动 |
| timeout_error | 请求超时，请稍后重试 |
| stream_error | 生成中断，请稍后重试 |
| unknown_error | 系统暂时不可用，请稍后重试 |

## 4. BFF 调用 Agent

推荐 Agent 接口：

```text
POST /agent/chat
```

BFF 转发请求：

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "stream": true,
  "trace_id": "trace-001"
}
```

Agent 可以返回与 BFF 相同的 JSON 结构，也可以返回 SSE。BFF 必须把 Agent 响应适配成 Vue 能稳定消费的契约。

## 5. BFF 错误映射

| 来源 | BFF 映射 |
|---|---|
| 请求参数为空 | `empty_input` |
| Agent 返回无相关文档 | `no_relevant_context` |
| Agent 检索失败 | `retrieval_error` |
| Agent LLM 调用失败 | `llm_error` |
| Agent 服务不可达 | `network_error` |
| BFF 或 Agent 请求超时 | `timeout_error` |
| SSE 非正常结束 | `stream_error` |
| 未知异常 | `unknown_error` |

## 6. 可选文档导入接口

Q1 默认采用预置文档入库。若需要加分功能“Web 上传文档”，使用以下接口。

```text
POST /api/v1/documents/import
```

响应：

```json
{
  "trace_id": "trace-import-001",
  "document_id": "doc-001",
  "status": "processing",
  "message": "文档已接收，正在解析和入库"
}
```

状态查询：

```text
GET /api/v1/documents/{document_id}/status
```

响应：

```json
{
  "trace_id": "trace-import-001",
  "document_id": "doc-001",
  "status": "ready",
  "message": "文档已完成入库，可用于检索"
}
```

说明：

- Apache Tika 解析不在 Vue 中执行；
- BFF 只负责上传转发和状态查询；
- 文档解析、分块、向量化和存储由数据处理管线完成。

