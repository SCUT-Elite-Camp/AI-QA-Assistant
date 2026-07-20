# AI 智能问答系统需求文档 (Q1)

## 文档基本信息
- **项目名称**：AI 智能问答助手 (AI-QA-Assistant)
- **版本**：v1.0
- **适用对象**：需求文档编写者、后端开发工程师、上下文处理模块、需求一致性评审 agent
- **更新日期**：2026-07-12

---

# 第一部分：Web 层用户界面需求 (REQ-WEB)

## REQ-WEB-001 主页布局与问题模板
### 状态
明确
### 需求描述
主页面作为系统入口，需向未选择对话的用户展示欢迎词与快捷提问卡片。
- 页面顶部展示中文欢迎语。
- 页面中心区域展示若干推荐的快捷问答标签（如：“项目 Q1 阶段需要完成哪些功能？”、“如何切换模型？”等）。
- 用户点击快捷问题卡片时，系统应自动将问题填入输入框，并触发提问流程。
### 关联接口
无
### 权限
无需登录
### 输入
无
### 输出
- 欢迎语界面。
- 快捷问题卡片列表。
### 异常情况
无
### 验收标准
- 主页展示中文问候语。
- 展示快捷问题标签卡片。
- 点击快捷卡片能自动填入并发送消息。

---

## REQ-WEB-002 问答对话交互与快捷键
### 状态
明确
### 需求描述
对话交互核心区域需提供完整的问答流式展现与操作。
- 键盘快捷键支持：
  - `meta+o`（Windows 下为 `Win+o` 或 `Ctrl+o`）: 新建对话。
  - `meta+k`（Windows 下为 `Win+k` 或 `Ctrl+k`）: 唤起搜索/搜索对话。
- 对话区域在接收到新消息时，需平滑滚动到底部。
### 关联接口
无
### 权限
无需登录
### 输入
- `meta+o`: 新建对话指令。
- `meta+k`: 搜索唤起指令。
### 输出
- 对话窗口平滑滚动。
- 唤起搜索弹窗或创建新对话。
### 异常情况
无
### 验收标准
- 键盘输入快捷键 `meta+o` 成功重置当前对话状态并跳转至新建对话页。
- 键盘输入快捷键 `meta+k` 成功弹出全局搜索框。
- 对话过程中，随着内容流式输出，对话窗口自动平滑滚至最下方。

---

## REQ-WEB-003 消息操作 (复制/编辑/反馈/重新生成)
### 状态
明确
### 需求描述
用户可以对已有的消息进行如下操作：
- **复制**：点击复制按钮，复制消息纯文本。
- **编辑（仅限用户消息）**：双击或点击编辑按钮，可在输入框中修改已发送的内容，提交后会删除该消息之后的所有消息，重新生成回答。
- **反馈（仅限助手消息）**：点赞或点踩，表示对该回答的满意度。
- **重新生成（仅限助手消息）**：点击重新生成，删除当前助手消息，重新调用接口生成新的回答。
### 关联接口
- `POST /api/chats/[id]`
- `DELETE /api/chats/messages/[id]`
- `POST /api/chats/votes/[id]`
### 权限
登录用户 / 临时访客会话所有者
### 输入
- `action`: `'copy' | 'edit' | 'vote' | 'regenerate'`
- 针对 `edit`: `content` (修改后的文本)
- 针对 `vote`: `isUpvoted` (true/false)
### 输出
- 操作成功状态。
- 重新生成后的流式消息。
### 异常情况
- 场景：非本人消息或非本对话消息进行操作
  - 返回状态码：404 Chat not found
- 场景：编辑非用户发送的消息，或重新生成非助手发送的消息
  - 返回状态码：400 Bad Request
### 验收标准
- 助手消息旁展示复制、点赞、点踩和重新生成按钮；用户消息旁展示编辑按钮。
- 用户点击编辑并提交后，该消息之后的消息均被删除，并成功触发流式重新回答。
- 点击点赞/点踩能正确保存状态，图标高亮变化。

---

## REQ-WEB-004 侧边栏历史记录导航
### 状态
明确
### 需求描述
侧边栏需提供对话历史列表，方便用户在不同的对话之间切换。
- 侧边栏可以折叠或展开。
- 对话历史按照时间分组展示，如：“今天”、“昨天”、“上周”、“更早”。
- 鼠标悬停到单个对话条目上时，展示重命名和删除的按钮。
### 关联接口
- `GET /api/chats`
- `PATCH /api/chats/title/[id]`
- `DELETE /api/chats/[id]`
### 权限
登录用户 / 临时访客会话所有者
### 输入
无
### 输出
按时间分组的对话列表树形/扁平结构。
### 异常情况
无
### 验收标准
- 侧边栏能够一键折叠/展开。
- 历史记录按“今天/昨天/上周/更早”分类清晰显示。
- 悬停对话项时，重命名图标与删除图标正常渲染且可用。

---

## REQ-WEB-005 模型切换与配置
### 状态
明确
### 需求描述
用户可以通过模型选择器在对话框顶部切换当前使用的 AI 语言模型。
- 支持切换的模型包括：`Claude Haiku 4.5`、`Gemini 3 Flash`、`GPT-5 Nano`。
- 模型配置信息在用户发送新消息时作为参数一并传递给后端。
### 关联接口
`POST /api/chats/[id]`
### 权限
无需登录
### 输入
- `model`: 模型标识符（如 `claude-haiku-4.5`、`gemini-3-flash`、`gpt-5-nano`）。
### 输出
- UI 更新为对应选择的模型。
### 异常情况
- 场景：提交了不存在的模型
  - 返回状态码：400 校验异常（"Invalid model"）
### 验收标准
- 下拉菜单可正常选择三个模型。
- 切换模型后，接下来的对话请求发送的 `model` 参数为切换后的模型标识。

---

## REQ-WEB-006 主题样式与个性化
### 状态
明确
### 需求描述
系统应支持个性化样式定制，提升用户视觉体验。
- 支持明暗主题一键切换（Light / Dark mode）。
- 支持至少 17 种主色（Primary colors）以及中性色（Neutral colors）的自定义选择，UI 组件库应根据选择实时更新颜色主题。
### 关联接口
无
### 权限
无需登录
### 输入
- `theme`: `'light' | 'dark'`
- `primaryColor`: 颜色值
### 输出
- 界面风格实时应用新样式。
### 异常情况
无
### 验收标准
- 切换暗黑模式后，全站背景、字体颜色、边框等样式完美适配，无白边或看不清的情况。
- 切换主色后，按钮、聚焦边框、激活态标签的颜色相应改变。

---

## REQ-WEB-007 对话分享设置
### 状态
明确
### 需求描述
用户可以将自己的对话记录分享给其他人阅读。
- 支持将对话权限在公开（public）与私有（private）之间切换。
- 提供“复制链接”按钮，自动复制当前分享页面的绝对 URL 到剪贴板。
- 当对话设为私有时，非创建者访问该链接应返回 404 错误。
- 当对话设为公开时，任何人皆可通过链接只读查看该对话及消息历史。
### 关联接口
- `PATCH /api/chats/visibility/[id]`
- `GET /api/chats/[id]`
### 权限
仅对话所有者可修改权限；所有人（包括未登录用户）可查看公开对话。
### 输入
- `visibility`: `'public' | 'private'`
### 输出
- 对话可见性状态更新。
### 异常情况
- 场景：非所有者尝试修改可见性，或访问私有对话链接
  - 返回状态码：404 Chat not found
### 验收标准
- 分享菜单内，可以切换“公开/私有”选项。
- 私有状态下，在另一个无痕浏览器窗口访问该聊天链接展示“Chat not found”或 404 页面。
- 公开状态下，无痕窗口可以只读形式正常查看该对话内容与引用。

---

## REQ-WEB-008 流式消息 Markdown 与引用渲染
### 状态
明确
### 需求描述
对于助手返回的流式回答，前端需利用 Markdown 引擎（Comark + Shiki）进行实时排版渲染。
- 支持标准的 Markdown 语法（包括标题、加粗、无序/有序列表、代码块、内联代码）。
- 支持流式代码高亮渲染。
- 将回答中的文本引用标识（例如 `[1]`）转换为专属的组件 `:cite-mark{index="1"}`，点击引用标识时能够高亮跳转或查看对应的数据源内容。
### 关联接口
`POST /api/chats/[id]`
### 权限
无需登录
### 输入
- 原始 Markdown 流文本。
### 输出
- 渲染后的 HTML DOM。
### 异常情况
无
### 验收标准
- 代码块能够被正确高亮着色，且随着文本流追加而动态扩展。
- 文本中的 `[1]`、`[2]` 成功被转换为 clickable 引用标记组件，点击可定位至数据源卡片。

---

## REQ-WEB-009 智能工具调用渲染
### 状态
明确
### 需求描述
当 AI 生成的回答中包含工具调用（Tool Calling）输出时，前端应采用专门的 UI 组件替换默认的文本展示。
- **RAG 检索工具**：调用 `rag_search` 时，在消息底部渲染来源列表组件 (`Sources.vue`)，展示引用的文档标题、得分和内容片段。
- **图表展示**：如果工具输出为图表数据，渲染图表组件 (`Chart.vue`)。
- **天气卡片**：如果工具输出为天气信息，渲染天气组件 (`Weather.vue`)。
### 关联接口
`POST /api/chats/[id]`
### 权限
无需登录
### 输入
- 工具输入/输出事件流数据。
### 输出
- 图表、天气、或者来源卡片组件。
### 异常情况
无
### 验收标准
- 页面收到 RAG 数据后，Sources 组件展示匹配的数据源卡片，显示 doc_id、标题及得分。
- 收到特定图表/天气工具输出时，对应图表或天气卡片能够被渲染成富图形，而非 JSON 文本。

---

# 第二部分：Web 层后端 API 路由规范 (API-WEB)

## API-WEB-001 用户会话获取
### 状态
明确
### 接口路径
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
  *(若未登录，则 user 字段为空)*
### 异常情况
无
### 验收标准
- 访问该接口能返回当前 Cookie Session 中的用户信息。

---

## API-WEB-002 清理用户会话 (登出)
### 状态
明确
### 接口路径
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
- 请求此接口后，清除 httpOnly session 缓存，重定向至首页时，用户状态变为未登录。

---

## API-WEB-003 GitHub OAuth 登录授权
### 状态
明确
### 接口路径
`GET /auth/github`
### 权限
无需登录
### 输入
- Query 参数：
  - `code`: 授权码 (GitHub 回调时携带)
  - `state`: 状态校验参数 (GitHub 回调时携带)
### 输出
- 重定向至 GitHub 授权页面，或登录成功后重定向至系统首页 `/`。
### 异常情况
- 场景：GitHub 授权回调错误
  - 返回状态码：401 Unauthorized
- 场景：缺少环境变量配置 (`GITHUB_OAUTH_CLIENT_ID` 或 `GITHUB_OAUTH_CLIENT_SECRET`)
  - 返回状态码：500 Internal Server Error
- 场景：State 校验不匹配
  - 返回状态码：500 Internal Server Error
### 验收标准
- 未带 code 访问时重定向至 GitHub 授权页。
- 授权成功返回 code 后，后端成功用 code 交换 access_token，并拉取 GitHub 用户信息，记录 session，最后安全重定向至首页。

---

## API-WEB-004 获取历史会话列表
### 状态
明确
### 接口路径
`GET /api/chats`
### 权限
登录用户 / 临时访客会话所有者
### 输入
无
### 输出
- 200 OK
  ```json
  [
    {
      "id": "chat-uuid",
      "title": "对话标题",
      "visibility": "private",
      "createdAt": "2026-07-12T16:00:00Z"
    }
  ]
  ```
  *(按 createdAt 倒序排序)*
### 异常情况
无
### 验收标准
- 返回当前用户拥有的所有对话列表，按时间由近到远排序。

---

## API-WEB-005 创建新对话
### 状态
明确
### 接口路径
`POST /api/chats`
### 权限
登录用户 / 临时访客会话所有者
### 输入
- Body (JSON):
  - `input`: string (首条消息内容，必填)
### 输出
- 201 Created / 200 OK
  ```json
  {
    "id": "new-chat-uuid",
    "title": "",
    "userId": "user-uuid",
    "visibility": "private",
    "createdAt": "2026-07-12T16:00:00Z"
  }
  ```
### 异常情况
- 场景：创建失败
  - 返回状态码：500 Failed to create chat
### 验收标准
- 发送请求后，数据库 `chats` 表新增一条记录，同时 `messages` 表新增一条用户角色（role='user'）的消息。

---

## API-WEB-006 获取对话详情
### 状态
明确
### 接口路径
`GET /api/chats/[id]`
### 权限
创建者可访问任意状态；非创建者仅在 visibility='public' 时可只读访问。
### 输入
- 路径参数 `id`: 对话唯一标识
### 输出
- 200 OK
  ```json
  {
    "id": "chat-uuid",
    "title": "对话标题",
    "visibility": "private",
    "createdAt": "2026-07-12T16:00:00Z",
    "isOwner": true,
    "messages": [
      {
        "id": "msg-uuid",
        "chatId": "chat-uuid",
        "role": "user",
        "parts": [{"type": "text", "text": "问题内容"}],
        "createdAt": "2026-07-12T16:00:01Z"
      }
    ]
  }
  ```
### 异常情况
- 场景：对话不存在，或者 visibility 为 'private' 且访问者非所有者
  - 返回状态码：404 Chat not found
### 验收标准
- 能够拉取指定对话的全部消息列表，并按时间升序排列。
- 判定 `isOwner` 是否为所有者。

---

## API-WEB-007 删除对话
### 状态
明确
### 接口路径
`DELETE /api/chats/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
### 输出
- 200 OK
  ```json
  [
    {
      "id": "chat-uuid",
      "title": "已删除标题"
    }
  ]
  ```
### 异常情况
- 场景：非对话所有者进行删除
  - 返回状态码：无返回或返回空数组 (安全设计：无法匹配到要删除的数据)
### 验收标准
- 调用删除接口后，数据库 `chats` 表中对应 id 数据被清除，且级联删除 `messages` 与 `votes` 中关联的数据。

---

## API-WEB-008 发送消息并流式获取 AI 回答
### 状态
明确
### 接口路径
`POST /api/chats/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
- Body (JSON):
  - `model`: string (模型名称，必须属于合法模型列表，必填)
  - `messages`: array (UI 消息数组，必填)
### 输出
- 200 OK (Content-Type: `text/event-stream` / UI stream response)
  - 输出格式符合 `ai` 库的 UI 消息流格式，包含 `text-start`, `text-delta`, `text-end`, `tool-input-available`, `tool-output-available` 等事件。
### 异常情况
- 场景：对话不存在或非该用户所有
  - 返回状态码：404 Chat not found
- 场景：模型参数非法
  - 返回状态码：400 Invalid model
- 场景：Agent 服务不可达或返回错误
  - 返回流式错误消息，前台正常报错展示
### 验收标准
- 接口在处理第一条消息时，若对话 title 为空，需自动截取前 25 个字符更新 title。
- 自动向 Python Agent 服务 `http://127.0.0.1:8000/api/chat` 发送 RAG 检索请求。
- 返回流式 SSE，首包渲染 tool-input 和 tool-output（承载 RAG 引用列表数据），后续逐步吐出 answer 文本。
- 流式结束后，必须将用户最新消息与 AI 的回答保存进数据库 `messages` 表。

---

## API-WEB-009 删除特定消息及后续历史
### 状态
明确
### 接口路径
`DELETE /api/chats/messages/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
- Body (JSON):
  - `messageId`: string (目标消息 ID，必填)
  - `type`: string (只能是 `'edit'` 或 `'regenerate'`，必填)
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
- 场景：目标消息不存在于该对话中
  - 返回状态码：404 Message not found
- 场景：`type` 为 `'edit'` 但要编辑的不是 user 消息；或 `type` 为 `'regenerate'` 但重生的不是 assistant 消息
  - 返回状态码：400 Bad Request
### 验收标准
- 若 `type` 为 `'edit'`，将从该用户消息的下一条消息开始删除直至最后。
- 若 `type` 为 `'regenerate'`，将从该助手消息（含当前消息）开始删除直至最后。

---

## API-WEB-010 重命名对话标题
### 状态
明确
### 接口路径
`PATCH /api/chats/title/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
- Body (JSON):
  - `title`: string (去除首尾空格，长度 1-100，必填)
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
- 场景：标题不合规
  - 返回状态码：400 Bad Request
### 验收标准
- 成功修改 `chats` 表中对应记录的 `title` 字段，并返回修改后的 chat 对象。

---

## API-WEB-011 修改对话分享可见性
### 状态
明确
### 接口路径
`PATCH /api/chats/visibility/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
- Body (JSON):
  - `visibility`: string (枚举类型 `'public' | 'private'`，必填)
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
- 场景：参数不属于枚举
  - 返回状态码：400 Bad Request
### 验收标准
- 成功修改 `chats` 表中对应记录的 `visibility` 字段，并返回修改后的对象。

---

## API-WEB-012 获取对话内所有评价数据
### 状态
明确
### 接口路径
`GET /api/chats/votes/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
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
- 返回当前对话下所有已被点赞/点踩的消息评分列表。

---

## API-WEB-013 提交消息点赞点踩评价
### 状态
明确
### 接口路径
`POST /api/chats/votes/[id]`
### 权限
仅限对话所有者
### 输入
- 路径参数 `id`: 对话唯一标识
- Body (JSON):
  - `messageId`: string (消息唯一标识，必填)
  - `isUpvoted`: boolean (若不传/传 undefined 代表取消评价)
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
- 场景：对非助手消息进行打分
  - 返回状态码：400 Can only vote on assistant messages
### 验收标准
- `isUpvoted` 值为 true/false 时插入/更新 `votes` 表数据。
- `isUpvoted` 为空或 undefined 时从 `votes` 中删除对应的记录。

---

# 第三部分：Agent 层智能问答需求 (REQ-AGT / API-AGT)

## API-AGT-001 Agent 健康检查
### 状态
明确
### 接口路径
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
- 接口能正常返回 status 信息。

---

## API-AGT-002 智能问答核心接口
### 状态
明确
### 接口路径
`POST /api/chat`
### 权限
无需登录 (Q1 阶段)
### 输入
- Body (JSON):
  - `query`: string (必填，用户提问，首尾去空后不能为空)
  - `top_k`: int (选填，检索数量，范围 1-20，默认 5)
  - `retrieval_mode`: string (选填，支持 'vector' | 'bm25' | 'hybrid'，默认 'hybrid')
  - `filters`: object (选填，过滤条件，预留)
  - `stream`: boolean (选填，是否流式，默认 false)
### 输出
- 200 OK
  ```json
  {
    "trace_id": "trace-xxxxxx",
    "status": "success",
    "answer": "根据上下文回答的内容 [1]。",
    "message": "",
    "citations": [
      {
        "citation_id": 1,
        "title": "文档标题",
        "source_url": "https://url...",
        "doc_id": "doc_001",
        "chunk_id": "doc_001::chunk_0",
        "score": 0.85,
        "snippet": "匹配的内容片段"
      }
    ]
  }
  ```
### 异常情况
- 场景：`query` 为空或空字符
  - 返回状态码：200 (状态标记为 `invalid_query`，不调用检索和 LLM)
- 场景：检索结果为空，或得分低于 `MIN_RETRIEVAL_SCORE`
  - 返回状态码：200 (状态标记为 `no_relevant_context`，不调用 LLM，提示无相关上下文)
- 场景：底层工具层异常
  - 返回状态码：200 (状态标记为 `retrieval_error`)
- 场景：LLM 服务异常或输出空答案
  - 返回状态码：200 (状态标记为 `llm_error`)
### 验收标准
- 输入空提问快速返回 `invalid_query`，无额外开销。
- 实装低相关过滤逻辑，当检索出的最高 score 低于阈值时，不扣减 LLM Token，直接返回 `no_relevant_context`。
- 无论返回何种 status，皆须输出 `trace_id` 供链路排查。

---

## API-AGT-003 Agent SSE 流式接口 (演示用)
### 状态
明确
### 接口路径
`POST /api/chat/stream`
### 权限
无需登录
### 输入
与 `POST /api/chat` 一致
### 输出
- 200 OK (Content-Type: `text/event-stream`)
- 包含事件：
  - `token`: `{"content": "流式切片文本"}`
  - `citations`: Citation 数组
  - `done`: `{"trace_id": "trace-xxx", "status": "success", "message": "", "citations_count": 1}`
### 异常情况
与 `/api/chat` 异常状态流一致，通过 `done` 事件回传最终 status 状态。
### 验收标准
- 响应头为 `text/event-stream`。
- SSE 能够正常吐出 token 切片直至 done 状态事件。

---

## REQ-AGT-001 可信回答与幻觉抑制
### 状态
明确
### 需求描述
Agent 层在组装 Prompt 调用 LLM 时，应采用严格的 RAG 约束，避免大模型胡乱编造事实。
- 检索到数据后，必须将它们拼接为 Prompt 上下文（Context）。
- Prompt 应强调“必须只根据提供的上下文回答，如果上下文中未提及，则说‘未在上下文中找到相关内容’，禁止基于常识编造数字、时间、负责人等”。
- 若检索结果均低于设定的阈值，则不将任何内容送入 LLM，在适配器层拦截并直接输出兜底文案。
### 验收标准
- Prompt 中包含强力幻觉抑制咒语。
- 低相关度检索（如最高 Score 小于系统设定的 `MIN_RETRIEVAL_SCORE`）时，直接进入兜底流程，不调用大模型。

---

## REQ-AGT-002 引用生成与一致性整理
### 状态
明确
### 需求描述
LLM 输出的文本中会包含引用标记（如 `[1]`），系统需实现一套清洗与标准化规则，保证前端解析出的引用编号与返回的 `citations` 数组完全一一对应。
- 从检索片段转换出对应 ID 为 `1, 2, ... N` 的 `citations` 列表。
- 答案整理（Answer Formatter）：
  - 若 LLM 输出了不存在的引用编号（例如仅返回 3 条数据，却写了 `[9]`），格式化工具需将其剔除或修正。
  - 若结论明显来源于某文献但没有加标，格式化工具需能够根据内容进行模糊补齐（如有必要）。
  - 清理乱码标记，规范化输出。
### 验收标准
- 返回的 JSON 报文中，`answer` 中的引用序号能且仅能在 `citations` 列表中找到对应项，不能出现越界序号。
- `citations` 的 `citation_id` 从 1 开始递增。

---

## REQ-AGT-003 Trace 链路追踪日志
### 状态
明确
### 需求描述
为了在分布式和异步架构中能排查问题，Agent 接收到请求后须立即创建唯一的 `trace_id`。
- 该 `trace_id` 贯穿整个请求周期：Web API -> Agent Layer -> Retrieval Adapter -> Tool Layer。
- 在日志输出中，必须携带 `[trace_id]` 前缀或字段，并记录下关键阶段：
  - `[RETRIEVAL_START]`：检索启动，记录 query、mode、top_k。
  - `[RETRIEVAL_END]`：检索完成，记录返回的 chunks 数量与总耗时。
  - `[RETRIEVAL_ERROR]`：检索异常，记录异常描述。
### 验收标准
- 日志文件及接口返回对象中，均可查询到格式统一的 `trace_id`（如 `trace-` + UUID/时间戳缩写）。
- 日志中检索阶段耗时记录清晰。

---

# 第四部分：工具集与检索适配需求 (REQ-TLS)

## REQ-TLS-001 检索适配器 (Retrieval Adapter)
### 状态
明确
### 需求描述
系统提供统一的适配层类 `RetrievalAdapter`，它负责协调本地 Mock 数据与工具层（Tool Layer）的物理检索服务，向上屏蔽底层存储的具体实现（如从 JSON 转换到 Milvus 数据库）。
- 支持一键开关 `USE_MOCK_RETRIEVAL`，当设为 false 时，自动动态导入真实工具集并执行。
### 验收标准
- 适配器能实现 `SearchTool.search()` 返回数据到 `RetrievalResult` 对象的模型映射。
- 检索底层错误被适配器捕获后，能够包装抛出标准自定义异常 `RetrievalError`。

---

## REQ-TLS-002 工具层检索规范 (SearchTool)
### 状态
明确
### 需求描述
工具层向 Agent 层暴露标准的接口契约以供调用。
- **接口定义**：
  ```python
  def search(
      query: str,
      top_k: int = 5,
      mode: str = "hybrid",
      filters: dict = None,
      min_score: float = 0.0,
      trace_id: str = None
  ) -> list[dict]
  ```
- **返回字典字段要求**：
  - `doc_id`: 文档唯一标识
  - `chunk_id`: 切片 ID（若底层无，自动生成为 `{doc_id}::chunk_{chunk_index}`）
  - `chunk_index`: 切片序号
  - `chunk_text`: 切片核心文本内容
  - `title`: 文档标题（若无，读取配置文件映射，仍找不到用 `doc_id` 兜底）
  - `score`: 综合检索得分 (0.0 - 1.0)
  - `source_url`: 原文链接（可为空）
### 验收标准
- 工具层导出的 `SearchTool` 能够被 Python 环境正常 `import`。
- 方法签名与字段完全符合契约，保证端到端契约测试（Contract Test）通过。

---

## REQ-TLS-003 多模式搜索与混合排序 (RRF)
### 状态
明确
### 需求描述
检索模块需提供三种基础检索模式，提升召回的准确率：
- **Vector 模式**：基于文本嵌入向量做余弦相似度匹配（当前测试环境以 TF-IDF 代替嵌入向量）。
- **BM25 模式**：基于传统词频与倒排文本算法进行匹配。
- **Hybrid 模式**：双路并发召回，并使用互惠排名融合（RRF, Reciprocal Rank Fusion）算法将两路排名列表进行合并去重。
- 合并去重的主键为 `(doc_id, chunk_index)`。
### 验收标准
- 模式参数传入 `hybrid` 时，能正确合并两路结果，且输出结果排序符合 RRF 算法预期。
- 重复切片（doc_id 和 index 均一致）在结果列表中已被成功去重。

---

## REQ-TLS-004 检索算法效果评估
### 状态
明确
### 需求描述
工具层需内置对检索召回指标的自动测评模块。
- 能够自动化读取标注测试集 `data/eval_questions.json`。
- 计算检索系统的常用评估指标：
  - `Hit Rate @ 1`、`Hit Rate @ 3`、`Hit Rate @ 5`（命中率）
  - `MRR` (Mean Reciprocal Rank，平均倒数排名)
- 测评后将结果导出为 JSON 报表存放在 `eval_results.json` 中。
### 验收标准
- 运行评估脚本能够跑通，并且能在本地持久化生成评测指标文件。

---

# 第五部分：数据持久化需求 (REQ-DAT)

## REQ-DAT-001 用户表实体模型 (users)
### 状态
明确
### 需求描述
记录通过 OAuth 登录进本站的外部用户信息。
### 字段定义
- `id`: string, 主键 (UUID)
- `email`: string, 邮箱 (非空)
- `name`: string, 姓名 (非空)
- `avatar`: string, 头像链接 (非空)
- `username`: string, GitHub 账号名 (非空)
- `provider`: string, 登录类型，仅限 `'github'` (非空)
- `providerId`: string, 外部渠道用户 ID (非空)
- `createdAt`: date-integer, 创建时间 (非空)
### 索引与唯一约束
- 唯一索引 `users_provider_id_idx` 复合键：`[provider, providerId]`。
### 验收标准
- 用户使用 GitHub 授权成功后，若用户首次登录，会在该表成功自动生成用户信息。

---

## REQ-DAT-002 对话会话表实体模型 (chats)
### 状态
明确
### 需求描述
记录用户创建的每一条独立问答会话的基本属性。
### 字段定义
- `id`: string, 主键 (UUID)
- `title`: string, 会话标题 (可为空，流式首轮提问后自动生成)
- `userId`: string, 关联 `users.id` 或临时会话所有者 ID (非空)
- `visibility`: string, 可见性枚举 `'public' | 'private'` (默认 `'private'`)
- `createdAt`: date-integer, 创建时间 (非空)
### 索引
- 索引 `chats_user_id_idx` 键：`[userId]`。
### 验收标准
- 正常创建会话时，记录插入成功。删除该记录时，应级联删除其下的所有消息和打分。

---

## REQ-DAT-003 对话消息表实体模型 (messages)
### 状态
明确
### 需求描述
记录每个会话里具体的往来提问与模型回答细节。
### 字段定义
- `id`: string, 主键 (UUID)
- `chatId`: string, 关联 `chats.id`，外键级联删除 (非空)
- `role`: string, 角色枚举 `'user' | 'assistant' | 'system'` (非空)
- `parts`: JSON, 内容主体片段（存储复杂对话的块格式，如文本和工具调用响应）
- `createdAt`: date-integer, 创建时间 (非空)
### 索引
- 索引 `messages_chat_id_idx` 键：`[chatId]`。
### 验收标准
- 发送与接收数据正常以 JSON 数组形式写入 `parts` 字段中。

---

## REQ-DAT-004 对话消息评分表实体模型 (votes)
### 状态
明确
### 需求描述
记录用户对助手模型某条回答的赞踩动作。
### 字段定义
- `chatId`: string, 关联 `chats.id`，外键级联删除 (非空)
- `messageId`: string, 关联 `messages.id`，外键级联删除 (非空)
- `isUpvoted`: boolean, 点赞为 true，点踩为 false (非空)
### 主键与唯一约束
- 复合主键：`[chatId, messageId]`。
### 验收标准
- 对同一条消息二次评分时，通过 `onConflictDoUpdate` 自动更新 `isUpvoted` 字段，不增加重复记录。

---

# 第六部分：待确认事项 (待确认)

> [!WARNING]
> 以下内容属于模糊需求或待讨论点，暂不作为强一致性开发依据，需要在后续迭代或会议中进行明确。

1. **真实 Tool Layer 正式版本上线时间**：目前工具集使用的是本地 JSONL 演示数据，未来何时将 vector 物理后端迁移至 Milvus 并接入真实的 HSBC Confluence 知识库？
2. **生产级大语言模型 (LLM) 选型**：在关闭 Mock 后，生产环境真实调用的 OpenAI-compatible 客户端应该接入哪一家服务商的什么具体模型（如 Qwen2.5、GPT-4o 还是私有部署的大模型）？
3. **真实 SSE Stream 协议改造**：目前的 Web Layer 对 Python Agent 的请求是阻塞式的一性获取 JSON 再模拟打字机流式输出。何时改造为 Agent 物理层也提供真实的 Streaming SSE 链路接入？
4. **共享访问权限细化**：对于 visibility 为 'public' 的对话，未来是否需要限制非所有者用户的点赞点踩操作，或者禁止非所有者重新生成？
5. **用户账号持久化与临时会话**：在不配置 GitHub OAuth 的开发环境下，当前自动使用临时随机 `session.id` 模拟 userId 体验，后续如何将访客历史迁移合并至真实用户账号下？
