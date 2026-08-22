# 04 Web 与 Agent 的内部 Memory 契约

## 目标

定义唯一的服务间 DTO，使 BFF 提供可信持久数据、Agent 提供纯记忆决策，公开 `ChatResponse` 保持兼容。此单元先冻结 schema、鉴权和 mock；不接入真实 Prompt。

前置：`01`、`02`、`03`。负责人：Web + Agent。后续依赖：`05`、`06`、`07`、`09`。

## 边界

浏览器只提交现有 `model/messages`。当 Web 的 `PERSISTENT_MEMORY_ENABLED=true` 且 actor 已认证时，BFF 解析身份并读取 Repository 后调用私有端点并提供仅服务端可用字段；其他所有情况仍调用公开 `/api/chat`，保持旧短窗兼容。若 Agent 自身开关关闭，私有端点必须返回固定 409 `persistent_memory_disabled`，BFF 记录不含正文的配置错误后仅重试一次公开 `/api/chat`。Agent 路由只有收到正确 `X-Agent-Internal-Token` 时才接受这些字段；没有该 header 的外部调用不能提供/覆盖 Memory 数据。

固定扩展 `agent/agent/schemas/chat.py`：

```text
InternalActor { user_id, authenticated: true }
MemoryMessage { id, sequence, revision, role, content }
MemorySnapshotInput { id, version, revision, covered_to_sequence, summary }
MemoryFactInput { id, category, value, expires_at }
MemoryContextInput { actor, chat_id, revision, current_message_id,
                     current_sequence, snapshot?, facts[], tail[] }
ChatRequest.memory_context?: MemoryContextInput
```

Agent 内部返回额外 `MemoryDecision`，但不得加到公开 `ChatResponse`：

```text
MemoryDecision {
  context_artifact?: { memory_brief, model_history, metadata }
  fact_proposals: FactProposal[]
  recall?: { handled, answer? }
}
```

为保持 schema 稳定，`fact_proposals` 字段在首版契约中预留；但从 `04` 到 `08` 必须返回空数组，且 Web 不得据此写入 Fact。只有 `09` 与 `09a` 完成后，才可启用 Fact proposal/confirm/revoke 生命周期。

唯一传输方式由 `04a` 固定：Web 调用受 token 保护的 `POST /api/internal/chat`，得到 `InternalChatResponse { response: ChatResponse, memory_decision }`；助手成功落库后再调用 `POST /api/internal/memory/compaction-plan`；编辑/删除成功后调用 `POST /api/internal/memory/reset-short-window` 清理仅用于兼容模式的进程短窗。不得使用 response header、全局状态、第二种副通道或公开 `/api/chat` 承载内部字段。

## 冻结 runtime 兼容边界（5955）

本契约的字段、三条 endpoint、`X-Agent-Internal-Token` 和公开 `ChatResponse` 边界保持不变。适配
`origin/agent-dev-infra@5955cd0` 时，仅改变 Agent 侧的接入方式：

- `agent.api.chat_routes.get_agent()` 已从 `ApplicationContainer` 取得应用级共享 Agent；internal router 必须复用该 dependency，不能重新 `Agent()`；
- `agent/app.py` 的 lifespan、`ApplicationContainer`、检索 warmup 和 `/ready` 必须原样保留；只允许额外注册 internal Memory router；
- `agent/runtime/lifecycle.py` 与 `agent/tools/executor.py` 是冻结 runtime 文件，不得为接入 Memory 而回退或覆盖；
- Deep Research 是独立模块。内部 Memory 请求只服务 Chat，不能携带 Research ID、不能触发 Research Job，也不能调用 `agent/deep_research/**`。

## 实施步骤

1. Web 新建 `memoryContract.ts`，Agent 新建对应 Pydantic DTO；字段、枚举、null 语义和时间格式必须逐项一致。
2. 为 Agent 添加 `AGENT_INTERNAL_TOKEN` 设置项；使用常量时间比较，缺失/错误 header 返回 403。Web 只从环境变量读取 token。
3. BFF 路由选择固定如下：仅当 Web `PERSISTENT_MEMORY_ENABLED=true`、actor 已认证且用户消息已持久化时，通过 Repository 构造 `memory_context` 并调用私有端点；否则调用公开 `/api/chat`，且不传任何内部字段。私有端点返回 `409 persistent_memory_disabled` 时，BFF 只记录配置错误并仅重试一次公开 `/api/chat`；其他私有端点错误按 `11` 的降级矩阵处理，不可把内部字段发送到公开端点。
4. Agent 验证 `current_message_id/current_sequence` 与 Tail 的 revision/sequence 一致；无效输入视为内部契约错误并安全降级，不可相信其中的 user ID。
5. 实现 `04a` 的三个私有端点、token dependency 与 mock contract tests；internal router 中的 `Agent` dependency 必须复用 `chat_routes.get_agent()`。公开 `/api/chat` 仅保留旧兼容请求，不读取任何 browser 传来的 `memory_context`。
6. 更新 `agent/docs/API_CONTRACT.md` 或新建同级内部契约文档，明确公开 JSON 的五个核心字段不变。

## 验收

- DTO 双端样例可序列化/反序列化；未知字段与错误枚举被拒绝。
- 没有内部 token 的请求不能注入 Fact、Snapshot、actor。
- BFF 发出的 Memory input 与 owner chat/revision 一致。
- Web 开关关闭或匿名 actor 时，BFF 固定走公开 `/api/chat`，不调用任何私有 Memory endpoint；Agent 返回固定 409 时，BFF 恰好回退一次公开调用且不泄露内部字段。
- 公开 `/api/chat` 的 answer/status/citations 契约无破坏性变化。

## 停止条件

若当前 checkout 不是精确的 `5955cd0`，或 `ApplicationContainer -> get_agent() -> Agent.chat()` 的实际路径无法用源码和测试确认，只能提交 DTO/mock/contract；不得修改 `agent.py`、`orchestration/orchestrator.py`、`runtime/runner.py` 的最终接线。
