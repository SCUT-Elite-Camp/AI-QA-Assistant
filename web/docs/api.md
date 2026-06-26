# BFF API 文档

本文档记录 Q1 Mock 阶段前端需要直接对接的 Spring Boot BFF API 契约。

## 基础地址

```text
http://localhost:8080
```

前端进行第一周 BFF 闭环验收时，在 `.env.local` 中使用：

```bash
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://localhost:8080
VITE_CHAT_PATH=/api/v1/chat
```

## 健康检查

```http
GET /api/v1/health
```

用于确认 BFF 服务是否已启动。

## 聊天接口

```http
POST /api/v1/chat
```

### 请求示例

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "stream": false
}
```

### 请求字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| query | string | 是 | 用户问题 |
| session_id | string | 否 | 会话 ID |
| stream | boolean | 否 | Q1 阶段固定使用 `false`，不实现流式输出 |

### 响应示例

```json
{
  "trace_id": "3073ef49-ce34-47ef-92d1-665ae62f02f8",
  "status": "success",
  "answer": "项目 Q1 阶段的核心目标是完成 AI 智能问答助手的最小可用闭环。Web 层需要支持用户输入问题、调用后端 BFF 接口、展示助手回答、展示引用来源，并在异常情况下给出友好的错误提示。当前阶段重点不是完整 Agent 能力，而是先跑通从前端到 BFF，再到 Mock Agent 响应的端到端链路。",
  "citations": [
    {
      "title": "HTC Q1 MVP Requirement",
      "source_url": "https://example.com/htc/q1",
      "snippet": "Q1 阶段目标是完成问答链路 MVP，包括输入、回答展示、引用来源和异常提示。"
    }
  ]
}
```

### 响应字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trace_id | string | 每次请求生成的追踪 ID |
| status | string | 当前 Mock 阶段返回 `"success"` |
| answer | string | 助手回答 |
| citations | array | 引用来源列表 |
| citations[].title | string | 引用标题 |
| citations[].source_url | string | 引用链接 |
| citations[].snippet | string | 引用摘要 |

### 错误说明

- `query` 为空或全是空格时，BFF 返回 400。
- 前端需要展示中文错误提示。
- 网络异常时，前端不能白屏。
