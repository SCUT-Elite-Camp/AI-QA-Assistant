# AI 智能问答助手

基于 **Vue 3 + TypeScript + Nuxt UI + AI SDK + Nitro** 的全栈智能问答应用。

[![Nuxt UI](https://img.shields.io/badge/Made%20with-Nuxt%20UI-00DC82?logo=nuxt&labelColor=020420)](https://ui.nuxt.com)
[![Nitro](https://img.shields.io/badge/Built%20with-Nitro-ff637e?logo=nitro&labelColor=18181B)](https://nitro.build)

## 功能

- ⚡️ **AI 流式对话** — 基于 [AI SDK](https://ai-sdk.dev) 的流式问答，支持 thinking/reasoning
- 🤖 **多模型支持** — Claude Haiku 4.5 / Gemini 3 Flash / GPT-5 Nano（通过 Vercel AI Gateway）
- 🔍 **Web 搜索** — 内置搜索工具（Anthropic、OpenAI）
- 📊 **图表和天气** — Tool Calling 富 UI 渲染
- 🔐 **GitHub OAuth 认证** — Nitro httpOnly Cookie 会话
- 💾 **对话历史持久化** — SQLite / Turso + Drizzle ORM
- ✨ **Markdown 渲染** — 流式代码高亮 (Comark + Shiki)
- 🎨 **明暗主题** — 17 种主色可切换
- ⌨️ **键盘快捷键** — meta+o 新建对话, meta+k 搜索
- 📂 **可折叠侧边栏** — 对话历史按时间分组
- 📤 **对话分享** — public/private + 复制链接
- 👍 **消息反馈** — 赞/踩 + 编辑 + 重新生成
- 🧪 **Mock 模式** — 无 API Key 时自动使用本地 Mock

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | Vue 3.5 + TypeScript 6.0 |
| 构建工具 | Vite 7.3 |
| UI 组件库 | Nuxt UI 4.8 (125+ Tailwind 组件) |
| AI 集成 | @ai-sdk/vue + Vercel AI Gateway |
| 后端 | Nitro 3.0 (内嵌 Vite) |
| 数据库 | SQLite/Turso + Drizzle ORM |
| 认证 | GitHub OAuth + httpOnly Session |
| 验证 | Zod |
| Markdown | Comark + Shiki |

## 项目结构

```text
htc-web/
├── src/
│   ├── pages/
│   │   ├── index.vue              # 首页：问候语 + 快捷问题
│   │   └── chat/[id].vue          # 聊天页：AI 对话核心
│   ├── components/
│   │   ├── chat/
│   │   │   ├── ChatTitle.vue      # 对话标题/重命名
│   │   │   ├── ChatVisibility.vue # 分享设置
│   │   │   ├── Indicator.vue      # 动画加载指示器
│   │   │   ├── Comark.ts          # Markdown 渲染器
│   │   │   ├── message/
│   │   │   │   ├── MessageContent.vue  # 消息内容（reasoning/text/tool）
│   │   │   │   ├── MessageActions.vue  # 复制/赞/踩/重新生成/编辑
│   │   │   │   └── MessageEdit.vue     # 内联编辑
│   │   │   └── tool/
│   │   │       ├── Chart.vue      # 图表渲染
│   │   │       ├── Weather.vue    # 天气卡片
│   │   │       └── Sources.vue    # 搜索来源
│   │   ├── Navbar.vue
│   │   ├── UserMenu.vue           # 用户菜单（主题/外观/登出）
│   │   ├── ModelSelect.vue        # 模型选择器
│   │   └── Modal*.vue             # 弹窗组件
│   ├── composables/
│   │   ├── useMockChat.ts         # Mock 桥接层
│   │   ├── useChats.ts            # 对话列表管理
│   │   ├── useChatActions.ts      # 重命名/删除
│   │   ├── useUserSession.ts      # 用户会话
│   │   └── ...
│   ├── mock/                      # Mock 降级系统
│   │   ├── mockAgent.ts           # Mock Agent 逻辑
│   │   └── errorMap.ts            # 中文错误映射
│   └── utils/                     # 工具函数
├── server/                        # Nitro 后端
│   ├── database/schema.ts         # Drizzle Schema
│   ├── routes/api/                # RESTful API
│   └── utils/tools/               # AI 工具定义
└── shared/utils/models.ts         # 模型列表
```

## 启动方式

```bash
# 安装依赖
pnpm install

# 启动开发服务器
pnpm dev
# → http://localhost:3000/

# 生产构建
pnpm build
pnpm preview
```

## 环境变量

复制 `.env.example` 为 `.env`：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VITE_USE_MOCK` | 是否使用 Mock 模式 | `true` |
| `AI_GATEWAY_API_KEY` | Vercel AI Gateway API Key | - |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App ID | - |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App Secret | - |
| `SESSION_SECRET` | 会话加密密钥 | 必填 |
| `TURSO_DATABASE_URL` | Turso 数据库地址 | 本地 SQLite |
| `TURSO_AUTH_TOKEN` | Turso 认证 Token | - |

- `VITE_USE_MOCK=true`：默认使用 Mock；设置为 `false` 时才请求真实 Agent
- Mock 模式下无需配置 `AI_GATEWAY_API_KEY`

## Mock 测试场景

| 输入 | 预期场景 |
|---|---|
| `你好` | 正常回答 + 引用来源 |
| `无相关` | 无相关上下文 |
| `检索异常` | 检索服务异常 |
| `模型异常` | 模型服务异常 |
| `网络异常` | 网络错误 |
| `超时` | 请求超时 |
| `请用流式回答` | 流式增量输出 |
| `流式异常` | 流式生成中断 |
| `无链接` | citation 无外部链接 |

## 接入真实 AI

1. 在 `.env` 中设置 `VITE_USE_MOCK=false`
2. 配置 `AI_GATEWAY_API_KEY`
3. 刷新页面即可切换到真实 AI 对话模式

## 手工演示检查

- [ ] 首页展示中文问候语和快捷问题标签
- [ ] 输入问题后创建对话并跳转
- [ ] 流式回答逐步展示
- [ ] 消息操作：复制 / 赞 / 踩 / 重新生成 / 编辑
- [ ] 侧边栏对话历史按时间分组（今天/昨天/上周/上个月）
- [ ] 重命名 / 删除对话
- [ ] 对话分享（公开/私有 + 复制链接）
- [ ] 模型切换（Claude / Gemini / GPT）
- [ ] 暗色/亮色主题切换
- [ ] 主色/中性色自定义
- [ ] 快捷键 meta+o 新建对话, meta+k 搜索
- [ ] Mock 错误场景正常展示（不白屏）

## 当前限制

- 真实流式对话需要配置 AI Gateway API Key
- 对话历史默认使用本地 SQLite，部署时建议使用 Turso
- Web Layer 不包含真实 RAG、LLM、PDF 解析、embedding 或 Milvus 集成
