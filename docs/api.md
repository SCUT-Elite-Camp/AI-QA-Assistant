# AI 智能问答系统 API 接口文档 (Q1)

## 文档基本信息
- **项目名称**：AI 智能问答助手 (AI-QA-Assistant)
- **版本**：v1.0
- **适用对象**：前端开发工程师、后端开发工程师、需求一致性评审 agent
- **更新日期**：2026-07-12

---

# 第一部分：Web 层后端 API 接口 (API-WEB)

## API-WEB-001 获取当前用户会话
### 状态
明确
### 关联接口
`GET /api/session`
### 权限
无需登录
### 输入
无
### 输出
- 200 OK
  ```json
  {
    "user": {
      "id": "12345",
      "username": "github-username",
      "name": "User Name",
      "avatar": "https://avatar-url..."
    }
  }
  ```
  *(若未登录，则 user 字段为 null 或不返回)*
### 异常情况
无
### 验收标准
- 成功访问该接口时，若有 Cookie 会话则返回登录的 GitHub 用户信息。
- 若无会话，则返回的 `user` 属性为空。

---

## API-WEB-002 清理当前会话 (登出)
### 状态
明确
### 关联接口
`DELETE /api/session`
### 权限
仅限登录用户
### 输入
无
### 输出
- 200 OK
  ```json
  {
    "success": true
  }
  ```
### 异常情况
无
### 验收标准
- 发送 DELETE 请求后，后台清除 httpOnly 的 session 数据，前端登录状态清空。

---

## API-WEB-003 GitHub OAuth 登录回调与重定向
### 状态
明确
### 关联接口
`GET /auth/github`
### 权限
无需登录
### 输入
- Query 参数：
  - `code` (string, 选填，GitHub 授权码)
  - `state` (string, 选填，用于防止 CSRF 攻击的随机校验字串)
### 输出
- 若未携带 `code`，重定向至 GitHub 官方 OAuth 页面进行授权。
- 若携带合法 `code`，回调成功后将用户信息写入 session 并重定向回 `/` 首页。
### 异常情况
- 场景：GitHub 回调时返回错误 (如用户拒绝授权)
  - 返回状态码：401 Unauthorized
- 场景：服务端未配置 `GITHUB_OAUTH_CLIENT_ID` 或 `GITHUB_OAUTH_CLIENT_SECRET`
  - 返回状态码：500 Internal Server Error
- 场景：State 校验不匹配
  - 返回状态码：500 Internal Server Error
### 验收标准
- 未带授权码访问，浏览器被正确重定向至 GitHub 认证地址。
- 回调携带正确授权码时，后端能顺利通过 code 换取 token 并拉取 GitHub 个人资料，最后写入 session 并跳转至首页。

---

## API-WEB-004 获取当前用户的对话历史列表
### 状态
明确
### 关联接口
`GET /api/chats`
### 权限
登录用户 / 临时访客会话所有者
### 输入
无
### 输出
- 200 OK (JSON 数组)
  ```json
  [
    {
      "id": "chat-id-uuid",
      "title": "如何使用 TypeScript",
      "visibility": "private",
      "createdAt": "2026-07-12T16:00:00.000Z"
    }
  ]
  ```
  *(按照 createdAt 降序排列)*
### 异常情况
无
### 验收标准
- 返回当前登录用户的所有历史对话项，且按创建时间由新到旧排序。

---

## API-WEB-005 创建新对话会话
### 状态
明确
### 关联接口
`POST /api/chats`
### 权限
登录用户 / 临时访客会话所有者
### 输入
- Body (JSON):
  - `input`: string (必填，首条发送的消息内容，去除空白后不能为空)
### 输出
- 200 OK / 201 Created
  ```json
  {
    "id": "new-chat-uuid",
    "title": "",
    "userId": "user-uuid",
    "visibility": "private",
    "createdAt": "2026-07-12T16:05:00.000Z"
  }
  ```
### 异常情况
- 场景：数据库写入失败
  - 返回状态码：500 Internal Server Error (Message: "Failed to create chat")
### 验收标准
- 成功发送请求后，数据库 `chats` 表增加新记录。
- 数据库 `messages` 表同步插入首条用户提问记录（role='user'）。

---

## API-WEB-006 获取对话会话详情
### 状态
明确
### 关联接口
`GET /api/chats/[id]`
### 权限
对话所有者可访问任意对话；非所有者仅在 visibility 为 'public' 时可以只读访问。
### 输入
- 路径参数 `id`: 对话 ID
### 输出
- 200 OK
  ```json
  {
    "id": "chat-uuid",
    "title": "对话标题",
    "visibility": "public",
    "createdAt": "2026-07-12T16:00:00.000Z",
    "isOwner": true,
    "messages": [
      {
        "id": "msg-uuid-1",
        "chatId": "chat-uuid",
        "role": "user",
        "parts": [{"type": "text", "text": "你好"}],
        "createdAt": "2026-07-12T16:00:01.000Z"
      }
    ]
  }
  ```
### 异常情况
- 场景：对话不存在，或者对话 visibility 为 'private' 且访问用户非创建者
  - 返回状态码：404 Chat not found
### 验收标准
- 能够返回该对话的完整信息，且 `messages` 列表按创建时间升序排列。
- 返回的 JSON 包含 `isOwner` 布尔属性，以识别当前用户是否拥有该对话。

---

## API-WEB-007 删除指定对话
### 状态
明确
### 关联接口
`DELETE /api/chats/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
### 输出
- 200 OK (返回被删除的对话信息)
  ```json
  [
    {
      "id": "chat-uuid",
      "title": "已删除标题"
    }
  ]
  ```
### 异常情况
- 场景：非所有者尝试删除或对话不存在
  - 返回状态码：无（数据库匹配不到记录，返回空数组）
### 验收标准
- 执行删除后，数据库中 `chats`、`messages` 和 `votes` 表关联的该对话数据被级联删除。

---

## API-WEB-008 发送消息并流式获取 AI 回答
### 状态
明确
### 关联接口
`POST /api/chats/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
- Body (JSON):
  - `model`: string (必填，使用的模型，必须匹配系统模型配置)
  - `messages`: array (必填，UI 消息历史列表)
### 输出
- 200 OK (Content-Type: `text/event-stream`)
  - 数据以流式事件传输，包含 `text-start`、`text-delta`、`text-end`、`tool-input-available`、`tool-output-available` 等。
### 异常情况
- 场景：对话不存在或非该用户所有
  - 返回状态码：404 Chat not found
- 场景：`model` 参数不在允许的列表中
  - 返回状态码：400 Invalid model
- 场景：调用 Python Agent API 异常
  - 通过 SSE 消息流返回包含 `Error:` 错误信息的文本片断。
### 验收标准
- 自动检测并截取首条提问为对话更新 title。
- 能够将大模型返回的 `[1]` 等标记转换成 `:cite-mark` MDC 格式。
- 将 RAG 结果（得分、文档 ID、标题、片段内容）映射为 `rag_search` 的 `tool-output` 传回前端。
- 在流式传输完毕后，自动将用户提问及助手回答完整保存入数据库。

---

## API-WEB-009 删除特定消息及后续历史 (用于编辑/重新生成)
### 状态
明确
### 关联接口
`DELETE /api/chats/messages/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
- Body (JSON):
  - `messageId`: string (必填，要编辑或重新生成的起始消息 ID)
  - `type`: string (必填，枚举值 `'edit' | 'regenerate'`)
### 输出
- 200 OK
  ```json
  {
    "success": true
  }
  ```
### 异常情况
- 场景：对话不存在
  - 返回状态码：404 Chat not found
- 场景：消息不存在于当前对话内
  - 返回状态码：404 Message not found
- 场景：编辑非用户消息，或重新生成非助手消息
  - 返回状态码：400 Bad Request
### 验收标准
- `type` 为 `'edit'` 时，保留当前消息，但将其在当前对话中后面的所有消息全部物理删除。
- `type` 为 `'regenerate'` 时，将当前消息及当前对话中后面的所有消息一并物理删除。

---

## API-WEB-010 重命名对话标题
### 状态
明确
### 关联接口
`PATCH /api/chats/title/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
- Body (JSON):
  - `title`: string (必填，长度 1-100，去除首尾空白后不能为空)
### 输出
- 200 OK
  ```json
  {
    "id": "chat-uuid",
    "title": "新标题"
  }
  ```
### 异常情况
- 场景：对话不存在
  - 返回状态码：404 Chat not found
- 场景：Title 长度超限或为空
  - 返回状态码：400 Bad Request
### 验收标准
- 成功修改 `chats` 表中对应记录的标题字段，并返回修改后的 chat 实体对象。

---

## API-WEB-011 修改对话可见性属性
### 状态
明确
### 关联接口
`PATCH /api/chats/visibility/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
- Body (JSON):
  - `visibility`: string (必填，枚举值 `'public' | 'private'`)
### 输出
- 200 OK
  ```json
  {
    "id": "chat-uuid",
    "visibility": "public"
  }
  ```
### 异常情况
- 场景：对话不存在
  - 返回状态码：404 Chat not found
- 场景：参数值非法
  - 返回状态码：400 Bad Request
### 验收标准
- 成功更改 `chats` 数据库记录中的 `visibility` 并返回更新后对象。

---

## API-WEB-012 获取当前对话的所有评分数据
### 状态
明确
### 关联接口
`GET /api/chats/votes/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
### 输出
- 200 OK
  ```json
  [
    {
      "chatId": "chat-uuid",
      "messageId": "msg-uuid",
      "isUpvoted": true
    }
  ]
  ```
### 异常情况
- 场景：对话不存在
  - 返回状态码：404 Chat not found
### 验收标准
- 能够返回对应 chatId 关联在 `votes` 表中的全部评分对象。

---

## API-WEB-013 提交助手消息评分
### 状态
明确
### 关联接口
`POST /api/chats/votes/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话 ID
- Body (JSON):
  - `messageId`: string (必填，目标助手消息 ID)
  - `isUpvoted`: boolean (选填，点赞传 true，点踩传 false，不传代表取消评分)
### 输出
- 200 OK
  ```json
  {
    "chatId": "chat-uuid",
    "messageId": "msg-uuid",
    "isUpvoted": true
  }
  ```
### 异常情况
- 场景：对话不存在或消息不存在
  - 返回状态码：404 Chat/Message not found
- 场景：对非 assistant 角色的消息进行打分
  - 返回状态码：400 Bad Request (Message: "Can only vote on assistant messages")
### 验收标准
- 传入 boolean 状态时，向 `votes` 写入/覆盖打分结果。
- 不传入 `isUpvoted` 时，从 `votes` 中物理删除评分记录，恢复未评分状态。

---

# 第二部分：Agent 层智能问答 API (API-AGT)

## API-AGT-001 Agent 服务健康检查
### 状态
明确
### 关联接口
`GET /health`
### 权限
无需登录
### 输入
无
### 输出
- 200 OK
  ```json
  {
    "status": "healthy"
  }
  ```
### 异常情况
无
### 验收标准
- 接口正常返回以验证 Python FastAPI 服务存活。

---

## API-AGT-002 智能问答核心接口
### 状态
明确
### 关联接口
`POST /api/chat`
### 权限
无需登录
### 输入
- Body (JSON):
  - `query`: string (必填，用户问题，首尾去空后不能为空)
  - `top_k`: int (选填，检索数量，范围 1-20，默认 5)
  - `retrieval_mode`: string (选填，支持 `'vector' | 'bm25' | 'hybrid'`，默认 `'hybrid'`)
  - `filters`: object (选填，检索过滤字段)
  - `stream`: boolean (选填，当前 Q1 均返回普通 JSON)
### 输出
- 200 OK
  ```json
  {
    "trace_id": "trace-xxxxxx",
    "status": "success",
    "answer": "根据检索内容回答的问题 [1]。",
    "message": "",
    "citations": [
      {
        "citation_id": 1,
        "title": "HSBC 流程指南",
        "source_url": "https://hsbc...",
        "doc_id": "doc_001",
        "chunk_id": "doc_001::chunk_0",
        "score": 0.88,
        "snippet": "具体的知识库切片内容"
      }
    ]
  }
  ```
### 异常情况
*(注意：Q1 阶段所有业务级报错统一在 JSON 对象的 `status` 字段中体现，HTTP 状态码依然为 200)*
- 场景：`query` 去除首尾空格后为空
  - 返回对象中 `status` 被标记为 `'invalid_query'`，不调用底层 Retrieval 和 LLM。
- 场景：底层没有搜索到相关文档，或检索出的最高分低于阈值 `MIN_RETRIEVAL_SCORE`
  - 返回对象中 `status` 被标记为 `'no_relevant_context'`，不调用 LLM。
- 场景：检索适配器或工具服务异常
  - 返回对象中 `status` 被标记为 `'retrieval_error'`。
- 场景：大模型服务不可用或生成了空回答
  - 返回对象中 `status` 被标记为 `'llm_error'`。
### 验收标准
- 空提问能够即时返回 `invalid_query`。
- 当检索结果不足或分数过低时，实现精准过滤并直接输出 `no_relevant_context`，避免产生不必要的 LLM 调用。
- 接口的每次调用皆会在日志与回包中绑定唯一的 `trace_id`。

---

## API-AGT-003 Agent SSE 流式接口 (演示用)
### 状态
明确
### 关联接口
`POST /api/chat/stream`
### 权限
无需登录
### 输入
与 `POST /api/chat` 完全一致
### 输出
- 200 OK (Content-Type: `text/event-stream`)
- 支持推送的事件：
  - `token`: `{"content": "部分文本内容"}`
  - `citations`: Citation 数组
  - `done`: `{"trace_id": "trace-id-uuid", "status": "success", "message": "", "citations_count": 2}`
### 异常情况
- 发生检索或生成异常时，会在 `done` 事件的 payload 中体现最终的异常 `status` 状态值。
### 验收标准
- 响应头包含 `text/event-stream`。
- 客户端能够读取到逐包发出的 token，直至 done 完成事件包。
