# AI 智能问答助手 · Web/BFF

2026-10-15：按用户要求，普通聊天和主题浏览直接读取已保存的快照，不再同步回源验证。列表、详情、收藏、主题摘要/文档列表/对话树继续检查本地账号、聊天归属和主题成员。来源更新或撤权不自动隐藏这些历史快照；再次问答、Memory 复用及引用原文 Reader 的实时校验保留。

基于 **Vue 3 + TypeScript + Nuxt UI + AI SDK + Nitro** 的全栈智能问答应用。

Deep Research searches all knowledge base documents the signed-in user can
currently access. Enable Deep Research, enter a question, then review and approve
the generated plan. No document selection is required. The BFF requests
`source_scope: {all_documents: true}`; the Agent freezes explicit authorized
document IDs and source versions before execution. Research prompts, controls,
activity messages and the source Reader are English.

2026-10-09 的服务端接入以[访问/证据契约](../docs/access-evidence/access-evidence-integration.md)为准。浏览器只调用同源 BFF，Python Agent 负责模型与检索；模型密钥不进入前端。完整联调见[运行手册](../docs/access-evidence/access-evidence-runbook.md)。

[![Nuxt UI](https://img.shields.io/badge/Made%20with-Nuxt%20UI-00DC82?logo=nuxt&labelColor=020420)](https://ui.nuxt.com)
[![Nitro](https://img.shields.io/badge/Built%20with-Nitro-ff637e?logo=nitro&labelColor=18181B)](https://nitro.build)

Chat streams the model's actual answer fragments into a transient preview after
current source checks. The final verified answer replaces the preview and is
saved for reloads; failed previews are cleared. The rightmost header control uses
panel-open/panel-close icons to toggle the retrieval monitor.

2026-10-15 Chat has independent Fast and Thinking pipelines; legacy `auto`
aliases Thinking. Fast performs original-query retrieval/fixed file preparation
and one generation, buffering evidence answers until citation checks pass.
The BFF skips post-turn Memory compaction for Fast, preserving its one-call budget.
Original image citations carry `content_kind=file` and file hash/version through
saved history and Reader; all existing source checks remain required. See the
[mode contract](../agent/docs/chat_mode_contract.md) for image configuration and limits.

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
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App ID | - |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App Secret | - |
| `SESSION_SECRET` | 会话加密密钥 | 必填 |
| `TURSO_DATABASE_URL` | Turso 数据库地址 | 本地 SQLite |
| `TURSO_AUTH_TOKEN` | Turso 认证 Token | - |
| `AGENT_BASE_URL` | Agent 层服务地址 | `http://127.0.0.1:8000` |
| `AGENT_API_KEY` | 调用 Agent 层业务接口的共享密钥（需与 Agent 层一致） | 必填 |
| `AGENT_INTERNAL_TOKEN` | 可信内部 Chat/Memory 请求 | 必填且与 Agent 一致 |
| `ATTACHMENT_INTERNAL_SECRET` | Agent `/private-files` 的内部凭据，地址复用 `AGENT_BASE_URL` | 启用附件/个人库时必填；加密 key 只由 Agent 使用 |
| `PERSISTENT_MEMORY_ENABLED` | Snapshot 与最近消息持久记忆 | 显式配置 |
| `AI_QA_BUILD_DIR/TOPICS_DATA_DIR` | 构建与 Topic 文件目录 | 可独立覆盖 |
| `SESSION_COOKIE_SECURE` | HTTPS secure Cookie；false 仅本机 HTTP 联调 | 生产 true |

- 不再以缺少 Gateway key 作为自动 Mock 开关；真实 Chat 使用 Agent 侧模型配置。
- Research UI mock 不验收原生权限、模型、检索或来源 Reader。真实联调必须关闭。
- 数据库执行完整 migration journal（包含 0015 lineage）。浏览读取历史快照；历史内容进入新模型上下文或衍生记忆时仍须验证来源。

> **Web → Agent 调用认证**：Web 调用 Agent 层 `/api/*` 业务接口时会自动附带
> `Authorization: Bearer <AGENT_API_KEY>` 请求头。该密钥必须与
> [`agent/README.md`](../agent/README.md) 中配置的 `AGENT_API_KEY` 一致，否则
> Agent 层返回 `401`。

## 本地验证

执行 `pnpm test`、`pnpm exec vue-tsc -p tsconfig.app.json --noEmit` 和 `pnpm build`。
组件/路由测试不代替真实模型与浏览器人工验收。三类来源、撤权、Reader 和 Topic
角色的实际 BFF HTTP 探针见根运行手册，结果见[整合报告](../docs/testing/integration/pr63-integration-acceptance.md)。

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
- [ ] 同角色可读，Topic viewer 不可写；本地账号/Topic 撤权阻断历史浏览，来源撤权阻断生成复用和引用原文读取
- [ ] 引用定位当前有权访问且版本匹配的实际原文
- [ ] 暗色/亮色主题切换
- [ ] 主色/中性色自定义
- [ ] 快捷键 meta+o 新建对话, meta+k 搜索
- [ ] 真实依赖故障清晰展示（不保存为成功答案）

## Retrieval monitor

The chat navbar opens an English retrieval monitor that follows the application's light/dark mode, primary color and neutral palette. Desktop layouts keep it beside the conversation; narrow screens show it over the chat without squeezing the message area.

Citation coverage counts returned answers with recorded `rag_search` citations, rather than claiming all retrieval attempts succeeded. Pending answers are excluded. The monitor supports All / Cited / Uncited filters and expandable chunk details. Only explicit vector similarity values are displayed as cosine percentages; absent scores or unavailable administrator-only index counts appear as “—”. A zero score or zero document count remains zero.

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
```

Research 已移除前端可执行 Mock，统一调用真实 BFF/Agent harness。计划审批后并行探索，
Reviewer 不通过时由独立 Agent 修订并复审，主 Agent 确认后才发布。
本地 Agent 可设置 `RESEARCH_DEVELOPMENT_MODE=true`、`HOST=127.0.0.1`，
使已登录且启用的用户拥有整个 Research 文件目录的访问权。此开关不由浏览器传入。

浏览器真实请求固定同源 `/api/research`，不使用 `VITE_RESEARCH_API_BASE` 直连 Agent。
源站撤权或版本漂移时，已保存研究报告与来源 Reader 也会被阻断。

正式 Research 详情页会同时读取 Job、`/progress` 和 `/events`。阶段、百分比、
任务状态及 Evidence/Claim 计数以 Agent 的 `research.progress.v1` 为准；最近活动
通过 `after_event_id` 增量游标更新，终态后停止轮询。


### Answer claim inspection (2026-10-20)

New Fast/Thinking evidence answers underline their server-bound assertions at normal weight.
Click or use Enter/Space to see supporting original quotes and document names;
multiple source passages appear separately. Introductions, bullet labels and
transitions remain ordinary text. The shared Prompt requests separate Markdown
bullets for multiple aspects rather than a compressed assertion paragraph. Open source document uses the existing
message-bound Reader and its current source checks. Markdown and citation widgets
are preserved. Quotes/titles saved in history follow the existing snapshot policy.
Old messages and unbound direct answers remain readable without added annotations.
The server validates and saves `data-answer-claims`; the browser cannot submit
assertion evidence for model use. No additional generation or schema migration is
required. See [Agent contract](../agent/docs/chat_mode_contract.md#clickable-answer-claims-2026-10-20).


Claim-linked answers now omit the old inline numbered citation badges. Assertion
underlines/dialogs provide the source entry point. The saved answer, citation
records and character offsets remain intact for verification, history and Reader;
only rendering hides the known markers, leaving literal code indices untouched.
Legacy answers without valid claim metadata retain their citation controls, and
Research citation rendering is unchanged.
