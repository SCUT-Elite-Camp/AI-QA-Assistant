# HTC Agent User Layer

本仓库是 HTC Agent Q1 Web 用户层 Demo。目标是在 2026-07-10 前完成一轮 RAG 问答闭环验证：

```text
用户提问 -> Vue 前端 -> Java Spring Boot BFF -> Agent 层 -> 检索工具 -> 知识库 -> LLM -> 答案和引用展示
```

当前仓库已有 Vue + Vite 前端 Demo。Q1 最新架构要求 Web 层包含两部分：

- Vue 前端：聊天页面、输入发送、流式展示、引用展示、异常提示、复制和清空。
- Java Spring Boot BFF：Web API、Mock、Agent 转发、SSE 透传、异常映射、trace_id、日志和 Demo 兜底。

Web 层不直接实现检索、Prompt、LLM、Apache Tika 文档解析、分块、向量化或向量存储。

## 文档入口

开发前先读：

- `docs/agent.md`：给人和 AI agent 的开发指令。
- `docs/api.md`：当前 Spring Boot BFF 的轻量级 API 契约。
- `docs/q1-three-phase-plan.md`：Q1 三阶段任务分工。
- `docs/api-contract.md`：Vue、Java Spring Boot BFF 和 Agent 的接口契约。
- `docs/vibe-guide.md`：每轮 vibe 开发时如何推进。
- `docs/july-demo-delivery-scope.md`：2026-07-10 Demo 必做、加分和暂缓功能。
- `docs/q1-web-architecture-refinement.md`：细化架构方案。

## Q1 三阶段

| 阶段 | 时间建议 | 目标 |
|---|---|---|
| 第一阶段 | 2026-06-18 到 2026-06-23 | 契约、骨架和 Mock 闭环 |
| 第二阶段 | 2026-06-24 到 2026-06-27 | 交互完善和异常补齐，任务量较少 |
| 第三阶段 | 2026-06-28 到 2026-07-10 | 真实联调、部署和 Demo 固化 |

## 前端快速启动

```bash
npm.cmd install
npm.cmd run dev
```

打开 Vite 输出的本地地址，默认通常是：

```text
http://127.0.0.1:5173/
```

## 前端验证

```bash
npm.cmd run typecheck
npm.cmd run lint
```

## Mock 场景

Q1 必须覆盖：

- 正常回答；
- 无相关文档；
- 检索异常；
- 模型异常；
- 网络异常；
- 请求超时；
- 流式中断；
- 引用无链接。

## BFF 接口

Vue 默认应调用 Java Spring Boot BFF：

```text
POST /api/v1/chat
```

请求体：

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "stream": false
}
```

响应体：

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

当前 BFF 轻量级接口以 `docs/api.md` 为准；跨层长期契约参考 `docs/api-contract.md`。

## 前后端联调说明

后端启动：

```bash
cd bff
mvn spring-boot:run
```

前端启动：

```bash
npm.cmd run dev
```

浏览器访问：

```text
http://localhost:5173
```

验收问题：

```text
项目 Q1 阶段需要完成哪些功能？
```

期望结果：

- 页面能显示 BFF 返回的 `answer`；
- 页面能显示 `citations`；
- 页面能显示 `trace_id`；
- 浏览器 Network 中请求地址应为：

```text
http://localhost:8080/api/v1/chat
```

## 环境配置

当前前端通过以下变量切换 Mock 和 Spring Boot BFF。`.env.example` 默认保留 `VITE_USE_MOCK=true`，便于真实链路不稳定时兜底演示；第一周 BFF 闭环验收时，请在 `.env.local` 中设置：

```bash
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://localhost:8080
VITE_CHAT_PATH=/api/v1/chat
```

代码当前只读取 `VITE_USE_MOCK`、`VITE_API_BASE_URL` 和 `VITE_CHAT_PATH`。真实 Agent 地址后续应由 Spring Boot BFF 转发适配，前端不要直接请求 Agent。

## Java Spring Boot BFF 约定

当前 BFF 位于：

```text
bff/
```

必须提供：

- `POST /api/v1/chat`
- 健康检查接口；
- Mock Profile 或配置开关；
- 统一 DTO；
- 统一异常映射；
- `trace_id` 日志；
- JSON 完整答案支持；
- SSE 透传或适配。

## Demo 最低成功标准

2026-07-10 前必须做到：

- 页面正常加载；
- 用户可以输入并发送问题；
- 空输入不会发送；
- 请求中不会重复提交；
- 系统能展示答案；
- 系统能展示 `trace_id`；
- 系统能展示 citations；
- `source_url` 为空时不生成无效链接；
- 能处理无相关文档、检索异常、模型异常、网络异常、超时和流式中断；
- 支持复制回答；
- 支持清空对话；
- 真实链路不可用时 Mock 仍能完成演示。
