# AI 智能问答助手 · Web/BFF

基于 **Vue 3 + TypeScript + Nuxt UI + AI SDK + Nitro** 的全栈智能问答应用。

2026-10-09 的服务端接入以[访问/证据契约](../docs/access-evidence-integration.md)为准。浏览器只调用同源 BFF，Python Agent 负责模型与检索；模型密钥不进入前端。完整联调见[运行手册](../docs/access-evidence-runbook.md)。

[![Nuxt UI](https://img.shields.io/badge/Made%20with-Nuxt%20UI-00DC82?logo=nuxt&labelColor=020420)](https://ui.nuxt.com)
[![Nitro](https://img.shields.io/badge/Built%20with-Nitro-ff637e?logo=nitro&labelColor=18181B)](https://nitro.build)

## 功能

- ⚡️ **AI 流式对话** — 基于 [AI SDK](https://ai-sdk.dev) 的流式问答，支持 thinking/reasoning
- 🔍 **多来源问答** — 企业 Confluence、个人库、对话附件与混合来源；模型由 Agent 服务端配置
- 🧾 **证据 Reader** — 回答绑定原文、版本、哈希，点击引用后按当前授权读取
- 🔬 **Research** — 独立创建、计划修改/批准、进度、报告、追问与下载；当前企业来源限定
- 🔐 **GitHub OAuth 认证** — Nitro httpOnly Cookie 会话
- 💾 **对话历史持久化** — SQLite / Turso + Drizzle ORM
- ✨ **Markdown 渲染** — 流式代码高亮 (Comark + Shiki)
- 🎨 **明暗主题** — 17 种主色可切换
- ⌨️ **键盘快捷键** — meta+o 新建对话, meta+k 搜索
- 📂 **可折叠侧边栏** — 对话历史按时间分组
- 📤 **对话/Topic 协作** — 当前会话与角色校验；public 状态不授予原始来源访问权
- 👍 **消息反馈** — 赞/踩 + 编辑 + 重新生成
- 🧪 **隔离测试** — Vitest/组件测试与显式 Research UI mock；真实验收不允许自动 mock 兜底

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | Vue 3.5 + TypeScript 6.0 |
| 构建工具 | Vite 7.3 |
| UI 组件库 | Nuxt UI 4.8 (125+ Tailwind 组件) |
| AI 集成 | @ai-sdk/vue + 可信服务端 Agent 客户端 |
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
│   │   ├── useResearchApi.ts      # 同源 Research BFF
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
| `VITE_RESEARCH_USE_MOCK` | 仅显式独立 Research UI 演示 | `false` |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App ID | - |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App Secret | - |
| `SESSION_SECRET` | 会话加密密钥 | 必填 |
| `TURSO_DATABASE_URL` | Turso 数据库地址 | 本地 SQLite |
| `TURSO_AUTH_TOKEN` | Turso 认证 Token | - |
| `AGENT_BASE_URL` | Agent 层服务地址 | `http://127.0.0.1:8000` |
| `AGENT_API_KEY` | 调用 Agent 层业务接口的共享密钥（需与 Agent 层一致） | 必填 |
| `AGENT_INTERNAL_TOKEN` | 可信内部 Chat/Memory 请求 | 必填且与 Agent 一致 |
| `ATTACHMENT_SERVICE_URL/INTERNAL_SECRET/ENCRYPTION_KEY` | 私有服务地址与密钥 | 启用附件/个人库时必填 |
| `PERSISTENT_MEMORY_ENABLED/SESSION_FACT_ENABLED` | 持久记忆与 Fact 功能 | 显式配置 |
| `AI_QA_BUILD_DIR/TOPICS_DATA_DIR` | 构建与 Topic 文件目录 | 可独立覆盖 |
| `SESSION_COOKIE_SECURE` | HTTPS secure Cookie；false 仅本机 HTTP 联调 | 生产 true |

- 不再以缺少 Gateway key 作为自动 Mock 开关；真实 Chat 使用 Agent 侧模型配置。
- Research UI mock 不验收原生权限、模型、检索或来源 Reader。真实联调必须关闭。
- 数据库执行完整 migration journal（包含 0015 lineage）。历史和衍生记忆缺证明时隔离。

> **Web → Agent 调用认证**：Web 调用 Agent 层 `/api/*` 业务接口时会自动附带
> `Authorization: Bearer <AGENT_API_KEY>` 请求头。该密钥必须与
> [`agent/README.md`](../agent/README.md) 中配置的 `AGENT_API_KEY` 一致，否则
> Agent 层返回 `401`。

## 本地验证

执行 `pnpm test`、`pnpm exec vue-tsc -p tsconfig.app.json --noEmit` 和 `pnpm build`。
组件/路由测试不代替真实模型与浏览器人工验收。三类来源、撤权、Reader 和 Topic
角色的实际 BFF HTTP 探针见根运行手册，结果见[整合报告](../docs/pr63-integration-acceptance.md)。

## 接入真实 AI

1. 配置 Agent 的真实模型、权限数据、原生 Confluence 绑定和检索依赖。
2. Web 与 Agent 配置相同 Bearer/internal token，Web SQLite 与 Agent 权限库路径一致。
3. 通过正常 Cookie 会话使用 UI；写操作使用 CSRF，浏览器不提供授权用户或历史证据。

## 手工演示检查

- [ ] 首页展示中文问候语和快捷问题标签
- [ ] 输入问题后创建对话并跳转
- [ ] 答案经授权校验与持久化后展示；无证据/校验失败有明确状态
- [ ] 消息操作：复制 / 赞 / 踩 / 重新生成 / 编辑
- [ ] 侧边栏对话历史按时间分组（今天/昨天/上周/上个月）
- [ ] 重命名 / 删除对话
- [ ] 同角色可读，Topic viewer 不可写；撤权后历史/收藏/引用不泄露
- [ ] 引用定位当前有权访问且版本匹配的实际原文
- [ ] 暗色/亮色主题切换
- [ ] 主色/中性色自定义
- [ ] 快捷键 meta+o 新建对话, meta+k 搜索
- [ ] 真实依赖故障清晰展示（不保存为成功答案）

## 当前限制

- Web 不直接运行 LLM/embedding/解析；这些服务必须实际可用。
- BFF 会缓冲 Agent SSE，经证明校验与落库后释放；不承诺未核验逐 token 输出。
- 没有以 244 项自动化测试代替全部上传格式、管理角色和布局的人工验收。

## Deep Research 接入

Deep Research 使用独立的长任务流程，不会由普通 Chat 自动触发。启动 Agent：

```bash
cd ../agent
uvicorn app:app --reload --port 8000
```

Web 环境变量：

```env
AGENT_BASE_URL=http://127.0.0.1:8000
AGENT_API_KEY=<server-only-shared-key>
AGENT_INTERNAL_TOKEN=<server-only-internal-token>
VITE_RESEARCH_USE_MOCK=false
```

前端独立开发时可以设置 `VITE_RESEARCH_USE_MOCK=true`，在不启动 Agent 的情况下验收创建、审批、执行进度和报告页面。正式联调必须切回 `false`。

浏览器真实请求固定同源 `/api/research`，不使用 `VITE_RESEARCH_API_BASE` 直连 Agent。
源站撤权或版本漂移时，已保存研究报告与来源 Reader 也会被阻断。

正式 Research 详情页会同时读取 Job、`/progress` 和 `/events`。阶段、百分比、
任务状态及 Evidence/Claim 计数以 Agent 的 `research.progress.v1` 为准；最近活动
通过 `after_event_id` 增量游标更新，终态后停止轮询。
