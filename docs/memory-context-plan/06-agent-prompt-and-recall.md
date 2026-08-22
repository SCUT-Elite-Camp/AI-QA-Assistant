# 06 Agent Prompt 注入与确定性 Fact 回忆

## 目标

在统一 Agent 基线中把 `ContextArtifact` 正确接入 Query Understanding 和 Runner Prompt；对显式回忆已确认 Fact 的请求走确定性回答，不让模型猜测。

本单元固定在 `06a` 的 `origin/agent-dev-infra@5955cd0` 上实施。新版 Runtime 的共享实例由 `ApplicationContainer` 持有；只能通过 `api/chat_routes.py:get_agent()` 取得，不能为了接入 Memory 改写 app lifespan、容器、工具执行器或 Deep Research。

前置：`05`、`06a`。负责人：指定 Agent 集成人。后续依赖：`07`、`09`。

## 允许修改范围

- `D:\project\AI-QA-Assistant\agent\agent\orchestration\orchestrator.py`
- `D:\project\AI-QA-Assistant\agent\agent\runtime\runner.py`
- `D:\project\AI-QA-Assistant\agent\agent\agent.py`
- 新建 `agent/agent/memory/memory_response_policy.py`
- 对应 unit/integration tests。

禁止修改：`agent/agent/runtime/lifecycle.py`、`agent/agent/tools/executor.py`、`agent/deep_research/**`、Web 的持久化实现，以及公开浏览器 ChatResponse。

## 实施步骤

1. Orchestrator：若 BFF 已提供可信 persistent context，调用 `ContextResolver` 得到 artifact；把 `artifact.model_history` 作为 history，并把必要的简短 context 交给 Query Understanding。否则仅走现有 `_read_history`。Resolver 只处理已验证的 DTO，不自行访问 Web 数据库、HTTP 或 Deep Research。
2. Runner：冻结基线的 `_build_messages()` 当前会把 `query_plan.standalone_query` 原文写进 system prompt，并把 `query_plan.original_query` 追加为 user message；当二者相同会重复当前问题。迁移时保持“基础/RAG system rules、Memory system context、Tail/history、当前 query”的总体顺序，但仅在 standalone 与 original 不同且确有检索解释价值时保留 standalone 原文；二者相同则不得写入该原文。最后只追加一次 `query_plan.original_query`。不要把 `memoryBrief` 拼入用户 query，也不要覆盖 citations 规则。必须覆盖 `original_query == standalone_query` 的回归：在最终 messages 的全部 `content` 中相同文本不得出现两次。
3. 新建纯函数 `MemoryResponsePolicy`：仅当用户有明确“之前确认的目标/偏好/计划是什么”语义时，读取已解析的 Confirmed Facts。存在则按类别确定性列出；不存在则确定性说明没有可见已确认事实。它不得查询数据库、不得生成 Fact、不得调用模型。
4. Agent 的私有 `/api/internal/chat` 返回 `InternalChatResponse`；其中 `response` 是原有 ChatResponse，`memory_decision.fact_proposals` 仅由 BFF 消费。`01` 至 `08` 阶段该数组必须固定为空，Fact proposal/confirm/revoke 只能由 `09` 启用。压缩计划不在此时返回，必须等助手消息成功落库后由 `07` 的专用端点生成。不能把 Fact metadata 暴露给普通浏览器响应。
5. 移除或隔离成功回答后的 `_save_conversation_turn()` 对 persistent session 的双写；持久路径的消息只由 Web 写，旧短窗兼容路径才保留它。

## 不变量与测试

- `memoryBrief`、Tail、当前 query 各自按设计出现，当前 query 不重复。
- RAG citation 检查仍在最终回答后执行；Fact 不生成 citation。
- 普通提问不因存在 Fact 自动回答个人资料；只有明确回忆触发确定性路径。
- 旧 Memory 开关关闭测试、QueryPlan、工具循环、citation tests 仍通过。
- 内部路由的测试通过 FastAPI dependency override 证明其复用共享 `get_agent()`；Chat 请求和 Memory 内部请求均不会创建 Deep Research Job。
- 运行 `06a` 基线的 Week-1 回归、目标 `pytest` 及新增 context/policy tests；未能运行时记录原因，不能写“通过”。

## 完成条件

实施分支必须先完成 `06b` 的人工对齐，并满足 `06a` 的基线断言；公开协议不变。若该已锁定基线的实际最终模型路径绕过 Runner，集成人把同一不变量接入实际最终模型调用点，并在交接中列出原因与测试，不得强行改旧 `_build_messages()`。
