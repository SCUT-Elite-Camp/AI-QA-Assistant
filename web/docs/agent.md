# Agent 开发指令

本文档是本项目进行 vibe 开发时给人和 AI agent 的工作说明。所有开发都以 2026-07-10 Q1 Demo 交付为目标。

## 项目目标

Q1 要完成一轮 RAG 问答闭环验证：

```text
用户输入问题
  -> Vue 页面发送请求
  -> Java Spring Boot BFF 接收并转发
  -> Agent 检索知识库并生成答案
  -> Web 页面展示答案、trace_id 和 citations
```

最低成功标准：

- 页面能正常加载；
- 用户能输入并发送问题；
- 系统能返回答案；
- 答案能展示来源引用；
- 异常时页面给出明确提示；
- 真实 Agent 不稳定时可切换 Mock 演示。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| Web 前端 | Vue + Vite | 当前仓库已有基础实现 |
| Web 后端 / BFF | Java Spring Boot | Q1 后端必须使用 Java 实现 |
| Agent 调用 | HTTP / SSE / fetch stream | 由 BFF 调用 Agent，Vue 不直连 Agent |
| Mock | 前端 Mock + BFF Mock | Demo 兜底和前后端独立开发 |
| 可选缓存 | Redis | Q1 只预留会话、限流、trace 调试等能力，不强行引入 |

## Web 层边界

Web 层包含：

- Vue 前端；
- Java Spring Boot BFF；
- Web API 契约；
- Mock 场景；
- 流式展示；
- citation 展示；
- 异常状态展示；
- Demo 兜底能力。

Web 层不负责：

- 文档解析；
- Apache Tika 入库实现；
- 分块和向量化；
- 向量存储；
- BM25 或向量检索算法；
- Prompt 编排；
- LLM 调用。

这些由数据处理管线、工具集和 Agent 层完成。

## 默认目录约定

当前仓库已有 Vue 代码：

```text
src/
  App.vue
  api/
  constants/
```

新增 Java Spring Boot BFF 时默认放在：

```text
server/
  src/main/java/
  src/test/java/
```

如果后续团队指定其他目录，以团队约定为准，但需要同步更新 README 和 docs。

## 开发优先级

1. 保证 Q1 必做功能。
2. 保证接口契约稳定。
3. 保证 Mock 可兜底演示。
4. 再做体验优化。
5. 最后考虑加分功能。

不允许为了加分功能影响主链路。

## 三阶段推进规则

1. 第一阶段：契约和 Mock 闭环。
   - 先让 Vue 调 BFF Mock 跑通。
   - 明确请求、响应、状态和 citations。
2. 第二阶段：交互和异常补齐。
   - 任务量稍轻，重点补齐页面体验和 Mock 异常。
   - 给真实 Agent 联调留缓冲。
3. 第三阶段：真实联调和 Demo 固化。
   - 接真实 Agent、SSE、部署和验收。

详细任务见 `q1-three-phase-plan.md`。

## 接口规则

Vue 只调用 BFF：

```text
POST /api/v1/chat
```

BFF 调用 Agent：

```text
POST /agent/chat
```

统一响应字段：

- `trace_id`
- `status`
- `answer`
- `citations`

统一状态枚举：

- `success`
- `empty_input`
- `no_relevant_context`
- `retrieval_error`
- `llm_error`
- `network_error`
- `timeout_error`
- `stream_error`
- `unknown_error`

接口细节以 `api-contract.md` 为准。

## 编码规则

Vue：

- API 调用集中在 `src/api/`；
- 状态提示集中在 `src/constants/`；
- 页面组件不要直接拼接 Agent 内部协议；
- SSE 解析逻辑要和组件展示逻辑分离；
- Mock 和真实请求保持同一响应模型。

Spring Boot BFF：

- 使用 Controller、Service、Client、DTO、ExceptionHandler、Config 分层；
- 使用 `WebClient` 调用 Agent；
- 使用 `ControllerAdvice` 统一异常映射；
- 每次请求必须有 `trace_id`；
- 日志必须包含 `trace_id`、`session_id`、`status`；
- SSE 透传时要处理 done、error、timeout 和客户端断开。

## 验收规则

每次完成一个任务，至少验证：

- 正常问答；
- 空输入；
- 无相关文档；
- 检索异常；
- 模型异常；
- 网络异常；
- 超时；
- 流式中断；
- 引用有链接；
- 引用无链接；
- 复制回答；
- 清空对话。

若真实 Agent 不可用，必须用 Mock 完成同样验收。

## 文档规则

每次 vibe 完成后：

- 更新 `vibe-log.md`；
- 如果接口变化，更新 `api-contract.md`；
- 如果阶段任务变化，更新 `q1-three-phase-plan.md`；
- 如果 Demo 范围变化，更新 `july-demo-delivery-scope.md`；
- 如果架构边界变化，更新 `q1-web-architecture-refinement.md`。

