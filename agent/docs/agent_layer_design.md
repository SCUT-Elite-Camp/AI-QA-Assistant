# Agent 层设计

Q1 版本采用单轮 RAG Agent：

用户请求 -> 参数校验 -> trace_id -> Retrieval Adapter -> Context Assembler -> Prompt Builder -> LLM -> Answer Formatter -> JSON 响应。

## 设计边界

- 只处理单轮问答。
- 只返回普通 JSON。
- Retrieval 默认使用 Mock，也支持按配置接入 Tool Layer `SearchTool.search()`。
- LLM 默认使用 Mock，也支持按配置接入 OpenAI-compatible Chat Completions 客户端。
- 不接真实 HSBC 系统，不处理真实客户、员工或权限数据。

## 模块职责

- `api`：Web 路由入口。
- `service`：Agent 主流程编排。
- `retrieval`：检索接口、Mock 检索和 Tool Layer 适配。
- `prompt`：上下文组装和 Prompt 生成。
- `llm`：LLM 抽象、Mock LLM 和真实 LLM Client。
- `formatter`：统一响应和 citations。
- `trace/logger/config/errors`：基础设施能力。

## 第二周接入点

- Web 请求可传 `retrieval_mode`，支持 `vector`、`bm25`、`hybrid`。
- `RetrievalAdapter` 在 Mock 模式下调用 `MockRetrieval.retrieve()`。
- `RetrievalAdapter` 在真实模式下动态加载 `tool_layer.SearchTool` 并调用 `search()`。
- Tool Layer 返回的 `dict` 会统一转换为 `RetrievalResult`。
- `ContextAssembler` 将标题、`doc_id`、`chunk_id` 和 `chunk_text` 写入 Prompt 上下文。
- `AnswerFormatter` 使用检索结果生成 citations。

## 第三周质量控制

- `ChatService` 在检索后执行相关度质量门禁，过滤低于 `MIN_RETRIEVAL_SCORE` 的结果。
- 检索为空或低相关时直接返回 `no_relevant_context`，不调用 LLM。
- 检索异常统一映射为 `retrieval_error`。
- LLM 异常或空输出统一映射为 `llm_error`。
- Prompt 模板明确要求只基于检索上下文回答，不使用外部常识补全。
- `AnswerFormatter` 会移除无效引用编号，并在缺少引用时补齐可用的 `[1]`。
- 日志记录 `trace_id`、阶段、检索模式、`top_k`、检索数量、状态和错误类型。
