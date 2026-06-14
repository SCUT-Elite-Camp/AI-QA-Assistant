# AI 智能问答助手 Web Layer MVP Demo

这是一个 Vue Web Layer Mock Demo，基于 Vue 3 构建，用于在 Agent Layer 接口稳定前演示基础问答链路。

用户可以输入自然语言问题，前端通过统一的 Agent API 层发起请求。默认情况下，Mock Agent 会返回回答、`trace_id` 和引用来源，并支持常见错误场景与流式输出模拟。

## 功能

- 自然语言问题输入
- Enter 发送，Shift + Enter 换行
- 用户消息与助手消息展示
- loading / generating 状态
- `trace_id` 展示
- citations 引用来源展示
- 正常回答、业务错误和本地错误模拟
- 流式回答模拟
- 复制助手回答
- 清空当前对话

## 技术栈

- Vue 3
- Vite
- JavaScript
- Mock Agent

## 项目结构

```text
src/
├─ api/
│  ├─ agentApi.js          # 统一 Agent API，集中切换 Mock / Real
│  └─ mockAgent.js         # Mock Agent 与流式模拟
├─ components/
│  ├─ ChatInput.vue        # 问题输入与发送
│  ├─ ChatWindow.vue       # 消息列表容器
│  ├─ ChatMessage.vue      # 用户/助手消息展示
│  └─ CitationList.vue     # 引用来源展示
├─ composables/
│  └─ useChat.js           # 聊天状态与发送流程
├─ utils/
│  └─ errorMap.js          # 状态与中文错误文案映射
├─ App.vue
├─ main.js
└─ style.css
```

## 启动方式

在 PowerShell 中进入项目目录：

```powershell
Set-Location "D:\project\HTC web"
npm install
npm run dev
```

浏览器打开：

<http://127.0.0.1:5173/>

生产构建：

```powershell
npm run build
```

## 环境变量

复制 `.env.example` 为本地 `.env` 后可调整配置：

```dotenv
VITE_USE_MOCK=true
VITE_AGENT_BASE_URL=http://localhost:8000
VITE_AGENT_CHAT_PATH=/api/chat
```

- `VITE_USE_MOCK`：默认使用 Mock；只有明确设置为 `false` 时才请求真实 Agent。
- `VITE_AGENT_BASE_URL`：真实 Agent 服务地址。
- `VITE_AGENT_CHAT_PATH`：真实 Agent 问答接口路径。

## Mock 测试问题

| 输入 | 预期场景 |
| --- | --- |
| `你好` | 正常回答、trace_id、引用来源 |
| `无相关` | 无相关上下文 |
| `检索异常` | 检索服务异常 |
| `模型异常` | 模型服务异常 |
| `网络异常` | 网络错误 |
| `超时` | 请求超时 |
| `请用流式回答` | 流式增量输出 |
| `流式异常` | 流式生成中断 |
| `无链接` | citation 无外部链接 |

## 手工演示检查

- [ ] 正常问题能展示用户消息和助手回答
- [ ] 助手消息展示 `trace_id`
- [ ] 正常 citation 展示标题、链接、文档和片段信息
- [ ] 无链接 citation 不生成空链接
- [ ] 空输入或纯空格不发送，并提示“请输入有效问题”
- [ ] Enter 发送问题
- [ ] Shift + Enter 输入换行
- [ ] 请求期间展示 loading 状态并防止重复提交
- [ ] 错误发生后页面不白屏，输入框恢复可用
- [ ] 流式回答逐步展示，结束后 loading 消失
- [ ] 复制按钮可复制助手回答
- [ ] 清空对话后恢复空状态

## 接入真实 Agent

UI 组件不会直接调用 `fetch`，也不需要知道当前使用的是 Mock 还是真实服务。Mock / Real 切换、请求参数标准化和真实 HTTP 请求统一由 `src/api/agentApi.js` 管理。

Agent 接口可用后：

1. 在本地 `.env` 中设置 `VITE_USE_MOCK=false`。
2. 配置 `VITE_AGENT_BASE_URL` 和 `VITE_AGENT_CHAT_PATH`。
3. 如果最终接口契约发生变化，只在 `agentApi.js` 中调整请求或响应适配。

真实 SSE 数据格式尚未确定。目前真实流式请求会回退到普通完整响应，Mock 模式仍支持流式增量展示。

## 当前限制

- 当前默认使用 Mock 数据。
- 对话历史不会持久化，刷新页面后会清空。
- Web Layer 不包含真实 RAG、LLM、PDF 解析、embedding 或 Milvus 集成。
- 真实流式协议仍需等待 Agent Layer 接口契约确认。
