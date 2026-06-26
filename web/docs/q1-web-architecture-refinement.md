# Q1 Web 层细化架构方案

本文档用于细化 2026 年 7 月 10 日 Q1 Demo 前 Web 用户层的架构方案。范围以 Web 层为主，同时明确 Web 与 Agent 层、工具集、数据处理管线、数据持久化层之间的接口依赖。

## 1. Q1 目标

Q1 阶段目标是完成一轮问答的基础功能验证，打通：

```text
用户提问 -> Web 用户层 -> Agent 层 -> 检索工具 -> 知识库数据 -> LLM 生成 -> Web 展示答案和引用
```

Q1 Demo 不追求完整生产系统，而是要证明 RAG 闭环可用、用户交互可演示、异常状态可控、后续扩展边界清晰。

## 2. Web 层边界

Web 层包含两个部分：

| 子模块 | 技术建议 | Q1 职责 |
|---|---|---|
| Vue 前端 | Vue + Vite | 聊天页面、输入发送、流式展示、引用展示、异常提示、复制和清空 |
| 用户层后端 / BFF | Java Spring Boot | Web API、Mock、Agent 转发、SSE 透传、异常映射、trace_id、日志、可选文档导入转发 |

Web 层不负责检索算法、Prompt 编排、LLM 调用、文档解析、向量化和存储。上述能力由 Agent 层、工具集、数据处理管线和数据持久化层完成。

## 3. 细化后的系统架构

```text
用户浏览器
  |
  | HTTP / SSE
  v
Vue 前端
  - 聊天页面
  - 输入与发送
  - 消息展示
  - 流式 token 渲染
  - 引用来源展示
  - 异常提示
  - Mock/真实模式切换
  |
  | /api/v1/chat
  | /api/v1/documents/import   可选
  v
Spring Boot 用户层后端 / BFF
  - 参数校验
  - session_id 管理
  - trace_id 生成或透传
  - Mock 场景
  - Agent 请求转发
  - SSE 流式透传
  - 异常状态转换
  - 结构化日志
  - 可选文档导入转发
  |
  | /agent/chat
  v
Agent 层
  - 请求入口
  - 上下文组装
  - 单步调用检索工具
  - LLM 调用
  - 答案生成
  - citation 组装
  - 异常处理
  |
  | 调用检索工具
  v
工具集
  - 统一检索入口
  - BM25 关键词检索
  - 向量语义检索
  - 混合检索与结果融合
  - 检索质量评估与日志
  |
  | 读取向量 / 文档 / 元数据
  v
数据持久化层
  - 向量存储
  - 文档存储
  - 元数据存储

数据处理管线，离线或管理员触发：
本地文档 -> Apache Tika 解析 -> 清洗 -> 分块 -> 向量化 -> 写入持久化层
```

## 4. 用户问答链路

### 4.1 主流程

1. 用户在 Vue 页面输入自然语言问题。
2. Vue 生成或读取 `session_id`，调用 BFF 的 `/api/v1/chat`。
3. BFF 校验请求。如果没有 `trace_id`，BFF 生成一个。
4. BFF 在 Mock 模式下直接返回 Mock 数据；在真实模式下转发到 Agent 层。
5. Agent 调用检索工具，从知识库取回相关文档分块。
6. Agent 组装 Prompt，调用 LLM 生成答案。
7. Agent 返回 `answer`、`status`、`trace_id`、`citations`。
8. BFF 将 Agent 响应适配为 Web 统一契约。
9. Vue 展示答案、状态、trace_id 和引用来源。

### 4.2 流式输出

Q1 优先支持 SSE 或 fetch stream：

```text
Vue <- SSE/fetch stream <- Spring Boot BFF <- SSE/fetch stream <- Agent
```

Vue 负责增量渲染 token，不展示原始 SSE 内容。Spring Boot BFF 负责透传或适配事件格式。若 Agent 暂不支持流式，Q1 至少要支持完整答案一次性展示。

### 4.3 异常处理

Web 层统一展示以下状态：

| 状态 | 页面提示 |
|---|---|
| empty_input | 请输入问题 |
| no_relevant_context | 当前知识库没有足够信息回答该问题 |
| retrieval_error | 检索服务暂时不可用，请稍后重试 |
| llm_error | 模型服务暂时不可用，请稍后重试 |
| network_error | 网络连接异常，请检查服务是否启动 |
| timeout_error | 请求超时，请稍后重试 |
| stream_error | 生成中断，请稍后重试 |
| unknown_error | 系统暂时不可用，请稍后重试 |

异常发生时必须满足：

- 页面不白屏；
- loading 不无限持续；
- 输入框恢复可用；
- 保留或展示 `trace_id`；
- 用户可以继续发起下一次提问。

## 5. 文档入库链路

### 5.1 Apache Tika 的位置

Apache Tika 位于数据处理管线，不位于 Vue 前端，也不应由 Vue 直接调用。

```text
本地 PDF / DOCX / TXT
  -> Java 数据处理服务
  -> Apache Tika 解析文本和元数据
  -> 文档清洗
  -> 分块
  -> 向量化
  -> 写入向量存储、文档存储、元数据存储
  -> 检索工具可查询
```

### 5.2 Q1 Demo 建议

Q1 必须确保演示文档已经进入知识库。实现方式可以二选一：

| 方式 | 是否建议 Q1 必做 | 说明 |
|---|---|---|
| 后端脚本或管理员接口预置入库 | 建议必做 | 风险低，适合 2026-07-10 Demo |
| Web 页面上传文档并入库 | 加分功能 | 依赖文件上传、任务状态、解析失败处理，时间风险更高 |

如果需要现场展示“上传或导入文档后进入知识库”，Web 层需要增加文档导入入口，并由 BFF 转发给数据处理服务。

## 6. Web 层功能拆分

### 6.1 Vue 前端

Demo 必须完成：

- 页面正常加载；
- 展示标题、Demo 提示、聊天区、输入区、发送按钮；
- 用户可输入自然语言问题；
- Enter 发送，Shift + Enter 换行；
- 空输入和纯空格不发送；
- 请求过程中避免重复提交；
- 展示用户问题和助手回答；
- 展示 loading / generating 状态；
- 支持流式 token 增量渲染；
- 流式不可用时支持完整答案展示；
- 展示 `trace_id`；
- 展示 citations，包括编号、标题、链接或 `doc_id`、`chunk_id`；
- `source_url` 为空时不生成无效链接；
- 支持复制回答；
- 支持清空当前对话；
- 异常时展示清晰提示。

后续可做：

- 登录和权限 UI；
- 历史会话列表；
- 多轮对话上下文管理；
- 反馈按钮，如赞、踩、纠错；
- 文档预览和定位到原文片段；
- 多 Agent 状态可视化。

### 6.2 Spring Boot 用户层后端 / BFF

Demo 必须完成：

- 提供 `/api/v1/chat`；
- 校验 `query`、`session_id`、`stream`；
- 生成或透传 `trace_id`；
- 提供 Mock 模式；
- 转发真实 Agent 请求；
- 支持 JSON 完整答案；
- 支持 SSE 或 fetch stream 透传；
- 统一响应结构；
- 统一异常状态转换；
- 记录结构化日志；
- 配置跨域或代理；
- 提供健康检查；
- 提供 OpenAPI 或接口说明。

后续可做：

- 用户鉴权和权限透传；
- Redis 会话缓存；
- Redis 限流和防重复提交；
- 问答历史持久化；
- 用户反馈落库；
- 文档导入任务状态查询；
- 更完整的审计日志。

## 7. 接口契约

### 7.1 Vue 调用 BFF

建议路径：

```text
POST /api/v1/chat
```

请求：

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "stream": true
}
```

普通响应：

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

SSE 响应示例：

```text
data: {"type":"meta","trace_id":"trace-001","status":"generating"}

data: {"type":"token","token":"Q1 阶段"}

data: {"type":"token","token":"需要打通用户提问、检索、生成答案和展示引用。"}

data: {"type":"done","trace_id":"trace-001","status":"success","citations":[{"index":1,"title":"Q1 范围说明","doc_id":"doc-q1-scope","chunk_id":"chunk-001","source_url":"/documents/doc-q1-scope"}]}

data: [DONE]
```

### 7.2 BFF 调用 Agent

建议 Agent 提供：

```text
POST /agent/chat
```

BFF 需要 Agent 层提供：

- 请求字段定义；
- 响应字段定义；
- SSE 事件格式；
- 错误状态枚举；
- HTTP 状态码映射；
- 超时时间；
- `trace_id` 生成或透传规则；
- citations 结构；
- 异常模拟方式。

### 7.3 BFF 调用数据处理管线，可选

如果 Q1 展示 Web 上传文档，需要数据处理服务提供：

```text
POST /api/v1/documents/import
GET /api/v1/documents/{document_id}/status
GET /api/v1/documents
```

导入响应示例：

```json
{
  "trace_id": "trace-import-001",
  "document_id": "doc-001",
  "status": "processing",
  "message": "文档已接收，正在解析和入库"
}
```

Q1 如果只做预置文档入库，则 Web 层只需要知道：哪些文档已入库、固定演示问题是什么、citation 中的 `doc_id` 和 `source_url` 如何展示。

## 8. 三个 Q1 阶段

| 阶段 | 时间建议 | Vue 前端 | Spring Boot BFF | 验收结果 |
|---|---|---|---|---|
| 第一阶段 | 2026-06-18 到 2026-06-23 | 页面骨架、输入发送、消息展示、BFF API Client、基础 citations | `/api/v1/chat` Mock、trace_id、统一响应、CORS、健康检查 | Vue 到 Spring Boot BFF 的 Mock 闭环跑通 |
| 第二阶段 | 2026-06-24 到 2026-06-27 | Enter/Shift+Enter、空输入、防重复、复制、清空、异常提示、引用无链接 | Mock 全异常场景、异常映射、日志、超时 | 所有用户层 Mock 场景可演示 |
| 第三阶段 | 2026-06-28 到 2026-07-10 | 接入真实 BFF 流式响应、兼容完整答案、长回答和多引用适配、Demo 兜底 | 转发 Agent、SSE 透传、状态适配、部署配置、联调排查 | 真实 RAG 问答链路跑通并稳定演示 |

完整阶段任务见 `q1-three-phase-plan.md`。

## 9. 外部依赖

| 依赖方 | Web 层需要的信息 |
|---|---|
| Agent 层 | `/agent/chat` 接口、SSE 协议、status 枚举、trace_id、citations、异常模拟方式 |
| 工具集 | 无相关文档的判定规则、检索异常映射、citation 排序规则 |
| 数据处理管线 | 演示文档是否入库、文档标题、source_url、doc_id、chunk_id、可选导入接口 |
| 数据持久化层 | Web 不直接依赖，只需确认数据可被 Agent / 检索工具访问 |
| 项目负责人 | Demo 固定问题、验收清单、页面风格、部署地址、演示脚本 |

## 10. 可扩展性原则

- Vue 组件、API Client、SSE 解析器、状态映射、Mock 数据分离；
- BFF 按 Controller、Service、AgentClient、DTO、ExceptionHandler、Config 分层；
- Mock Client 与 Real Agent Client 使用同一响应模型；
- 接口路径使用版本号，如 `/api/v1/chat`；
- citations 使用数组，后续可扩展页码、片段内容、文件类型、权限字段；
- Redis 在 Q1 只作为预留或可选项，后续可用于会话、限流、缓存、trace 调试信息；
- Web 层不直接连接向量库、文档库或 Redis，避免与数据层耦合。
