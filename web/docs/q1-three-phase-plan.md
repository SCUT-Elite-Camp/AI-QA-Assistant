# Q1 三阶段任务分工

本文档把 Q1 Web 层工作拆成三个阶段，目标是在 2026-07-10 前交付可演示的 RAG 问答 Demo。Web 层包含 Vue 前端和 Java Spring Boot BFF。

## 阶段总览

| 阶段 | 时间建议 | 阶段目标 | 任务量 |
|---|---|---|---|
| 第一阶段 | 2026-06-18 到 2026-06-23 | 契约、骨架和 Mock 闭环 | 中等 |
| 第二阶段 | 2026-06-24 到 2026-06-27 | 交互完善和异常补齐 | 较少 |
| 第三阶段 | 2026-06-28 到 2026-07-10 | 真实联调、部署和 Demo 固化 | 较多 |

第二阶段故意安排得轻一些，用于吸收第一阶段遗留问题，并给第三阶段真实 Agent 联调留出缓冲。

## 第一阶段：契约、骨架和 Mock 闭环

### 阶段目标

完成 Vue 前端到 Java Spring Boot BFF 的基础闭环。即使 Agent 层还不可用，也能通过 BFF Mock 完成一次正常问答。

### Vue 前端任务

- 保留并整理现有 Vue + Vite 页面；
- 展示标题、Demo 提示、聊天区、输入区、发送按钮；
- 支持用户输入问题并发送；
- 展示用户消息和助手消息；
- 展示 loading / generating 状态；
- 建立统一 API Client；
- 前端默认调用 BFF 的 `/api/v1/chat`；
- 支持通过环境变量切换 Mock 或真实 BFF；
- 初步展示 `trace_id`；
- 初步展示 citations。

### Java Spring Boot BFF 任务

- 新建 Spring Boot 工程，默认目录为 `server/`；
- 提供 `POST /api/v1/chat`；
- 定义请求 DTO：`query`、`session_id`、`stream`；
- 定义响应 DTO：`trace_id`、`status`、`answer`、`citations`；
- 使用 Spring Validation 校验空输入；
- 生成或透传 `trace_id`；
- 提供正常回答 Mock；
- 配置 CORS 或本地代理；
- 输出基础结构化日志；
- 提供健康检查接口；
- 提供 OpenAPI 或接口说明。

### 文档任务

- 确认 `api-contract.md`；
- 确认 `agent.md`；
- 更新 README 中的启动方式和架构说明；
- 在 `vibe-log.md` 记录第一阶段进度。

### 外部依赖

- Agent 层确认最终 `/agent/chat` 请求和响应字段；
- 数据处理层提供至少一批 Demo 文档名称；
- 项目负责人确认固定 Demo 问题。

### 第一阶段验收

输入：

```text
项目 Q1 阶段需要完成哪些功能？
```

预期：

- Vue 页面展示用户问题；
- Vue 调用 Spring Boot BFF；
- BFF 返回 Mock 答案；
- 页面展示答案、`trace_id` 和至少一条 citation；
- 页面不白屏，loading 能正常结束。

## 第二阶段：交互完善和异常补齐

### 阶段目标

补齐 Q1 Web 用户层体验和异常场景。该阶段任务量较少，重点是让 Mock 演示足够稳定。

### Vue 前端任务

- Enter 发送；
- Shift + Enter 换行；
- 空字符串和纯空格不发送；
- 请求中禁止重复提交；
- 复制回答；
- 清空当前对话；
- 自动滚动到最新消息；
- 完整展示 citations；
- `source_url` 为空时不生成无效链接；
- 展示全部异常状态提示；
- 异常后输入框恢复可用。

### Java Spring Boot BFF 任务

- Mock 覆盖全部状态：
  - `success`
  - `no_relevant_context`
  - `retrieval_error`
  - `llm_error`
  - `network_error`
  - `timeout_error`
  - `stream_error`
  - 引用无链接
- 统一异常映射；
- 统一错误响应结构；
- 配置请求超时；
- 日志中记录 `trace_id`、`session_id`、`status`；
- 保证 Mock 响应和真实 Agent 响应结构一致。

### 文档任务

- 更新 `api-contract.md` 的状态枚举和错误示例；
- 更新 `july-demo-delivery-scope.md` 的验收状态；
- 在 `vibe-log.md` 记录 Mock 验收结果。

### 外部依赖

- Agent 层确认异常状态语义；
- 项目负责人确认页面错误提示文案是否可用于 Demo。

### 第二阶段验收

以下场景均可通过 Mock 演示：

- 正常回答；
- 空输入；
- 无相关文档；
- 检索异常；
- 模型异常；
- 网络异常；
- 请求超时；
- 流式中断；
- 引用无链接；
- 复制回答；
- 清空对话。

任何异常都不能导致页面白屏、死锁或无限 loading。

## 第三阶段：真实联调、部署和 Demo 固化

### 阶段目标

接入真实 Agent，完成 RAG 闭环演示，并在 2026-07-10 前固化 Demo 脚本、部署和兜底方案。

### Vue 前端任务

- 接入真实 BFF 地址；
- 支持 JSON 完整答案展示；
- 支持 SSE / fetch stream token 增量渲染；
- 处理 `meta`、`token`、`done`、`error` 事件；
- 流式结束后关闭 loading；
- 流式中断时展示 `stream_error`；
- 用户取消或页面卸载时中断请求；
- 长回答、多引用展示适配；
- Demo 屏幕尺寸适配；
- 保留 Mock 兜底开关。

### Java Spring Boot BFF 任务

- 使用 `WebClient` 调用 Agent；
- 转发 `/api/v1/chat` 到 Agent 的 `/agent/chat`；
- 支持 Agent JSON 响应；
- 支持 Agent SSE 响应透传或适配；
- 将 Agent 错误映射为 Web 状态；
- 透传或统一生成 `trace_id`；
- 配置连接超时、读取超时和总请求超时；
- 客户端断开时终止下游 Agent 请求；
- 提供健康检查；
- 提供部署配置；
- 保留 Mock 兜底 Profile 或配置开关。

### 文档任务

- 更新 `api-contract.md`，确保和真实 Agent 一致；
- 更新 `july-demo-delivery-scope.md` 的最终 Demo 脚本；
- 更新 README 的启动、配置和部署说明；
- 在 `vibe-log.md` 记录真实联调结果和风险。

### 外部依赖

- Agent 层提供可访问的测试地址；
- Agent 层提供 SSE 事件格式；
- 数据处理层确认 Demo 文档已经入库；
- 工具集确认固定问题能检索到结果；
- 运维或后端提供部署地址和环境变量。

### 第三阶段验收

真实链路满足：

```text
Vue -> Spring Boot BFF -> Agent -> 检索工具 -> 知识库 -> LLM -> Web 展示答案和引用
```

最终验收：

- 正常问题可生成答案；
- 答案带 citation；
- 能展示 `trace_id`；
- 流式可用时逐步展示；
- 流式不可用时完整答案可展示；
- 异常状态可控；
- Mock 兜底可用；
- 2026-07-10 Demo 脚本可连续演示。

## 分工建议

| 角色 | 主要任务 |
|---|---|
| Web 前端 | Vue 页面、状态、SSE 解析、引用展示、交互体验 |
| Web 后端 / BFF | Java Spring Boot、API、Mock、Agent 转发、异常映射、日志 |
| Agent 对接人 | 提供 Agent 接口、SSE 协议、状态枚举、测试地址 |
| 数据对接人 | 确认 Demo 文档入库、文档标题、doc_id、chunk_id、source_url |
| Demo 负责人 | 固定演示问题、验收清单、演示脚本和兜底方案 |

如果你一个人负责 Web 层，优先顺序是：

1. 先完成 Vue + BFF Mock 闭环；
2. 再补齐交互和异常；
3. 最后接真实 Agent 和部署。

