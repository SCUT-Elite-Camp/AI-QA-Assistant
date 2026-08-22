# 04 Web 与 Agent 的内部 Memory 契约

## 目标

定义唯一的服务间 DTO，使 BFF 提供可信持久数据、Agent 提供纯记忆决策，公开 `ChatResponse` 保持兼容。本单元只冻结 schema、开关、鉴权约束和 mock；不创建私有 HTTP endpoint，不接入真实 Prompt。

前置：`01`、`02`、`03`。负责人：Web + Agent。后续依赖：`05`、`06`、`07`、`09`。

施工位置：Web 证据位于 `D:\project\AI-QA-Assistant`（`web-dev`）；Agent DTO/配置只在
`D:\project\AI-QA-Assistant-agent-memory`（`agent-dev-infra`）实施。当前 Web 契约实现
已完成，只能审查；本单元当前待实施范围是 Agent DTO、配置和内部契约文档。三条私有端点、
token dependency、路由接线和端到端 contract tests 一律属于 `04a`。

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
InternalChatRequest { <现有 ChatRequest 字段>, memory_context: MemoryContextInput }
```

公开 `ChatRequest` 不增加 `memory_context`。只有 `InternalChatRequest` 可以携带它，并且
只能由 token 保护的 `04a` 私有路由解析；浏览器向公开 `/api/chat` 发送同名字段必须被拒绝。

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

## 允许修改范围

- `D:\project\AI-QA-Assistant-agent-memory\agent\agent\schemas\chat.py`
- `D:\project\AI-QA-Assistant-agent-memory\agent\agent\config\settings.py`
- `D:\project\AI-QA-Assistant-agent-memory\agent\.env.example`
- `D:\project\AI-QA-Assistant-agent-memory\agent\docs\API_CONTRACT.md`（或同级内部契约文档）
- 对应 DTO/config unit tests；Web 文件只允许审查既有契约证据。

禁止修改 `app.py`、`api/chat_routes.py`、新增 internal router、`agent.py`、`orchestration/orchestrator.py`、`runtime/runner.py` 或任何 Web 路由；这些接线在 `04a`、`06`、`07` 各自施工。

## 实施步骤

1. 审查既有 `web-dev` 的 `memoryContract.ts`，在 Agent 新建对应 Pydantic DTO；字段、枚举、null 语义和时间格式必须逐项一致。`InternalChatRequest` 与公开 `ChatRequest` 必须是独立类型；公开 `ChatRequest`/`ChatResponse` 不得因内部 DTO 改变。
2. 为 Agent 添加 `AGENT_INTERNAL_TOKEN` 与持久 Memory 开关设置项，默认关闭，并写明未来 `04a` 必须使用常量时间比较：缺失/错误 header 为 403，开关关闭为固定 409。此步只提供配置和 schema，不注册 dependency 或路由。
3. 更新内部契约文档并添加 DTO/config mock tests：未知字段、错误枚举和非法时间格式必须被拒绝；`memory_context` 只能属于内部 request 类型。BFF 路由选择、可信 actor/revision/Tail 校验和错误回退由 `04a` 实施。

## 验收

- DTO 双端样例可序列化/反序列化；未知字段与错误枚举被拒绝。
- 公开 `ChatRequest` 不包含也不能解析 `memory_context`；内部 DTO 才能表达 actor、Snapshot、Fact 和 Tail。
- 内部 DTO 清晰表达 owner chat/revision、current message 和 Tail 的校验所需字段；实际可信输入校验与 BFF 回退测试由 `04a` 验收。
- 公开 `/api/chat` 的 answer/status/citations 契约无破坏性变化。

## 停止条件

若 `5955cd0` 不再是 HEAD 的祖先，或除 docs 与 `06a` 记录的 `agent/requirements-week1.txt` 例外外出现未归属的 Agent 源码差异，只能提交 DTO/mock/contract；不得修改 `agent.py`、`orchestration/orchestrator.py`、`runtime/runner.py` 的最终接线。
