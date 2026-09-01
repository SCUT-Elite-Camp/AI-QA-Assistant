# 04a 唯一 Web-Agent 私有端点规范

## 目标

把 Memory 的服务间传输锁定为三条受 token 保护的 HTTP 接口，避免 header、副通道、全局变量和公开 ChatResponse 混用。BFF 是唯一调用者；浏览器永远不可访问这些端点。

前置：`04`。负责人：Web + Agent。后续：`05`、`06`、`07`、`09a-Web`。

施工位置：Agent endpoint 只在 `D:\project\AI-QA-Assistant-agent-memory`（`agent-dev-infra`）实施。
`D:\project\AI-QA-Assistant`（`web-dev`）中既有 BFF internal client、路由选择和单次回退
实现只作审查证据，不得重复施工；若审查发现它与本契约不一致，停止并单独报告跨层契约问题。

## 允许修改范围

- `D:\project\AI-QA-Assistant-agent-memory\agent\app.py`（仅注册 internal router；不得改 lifespan、warm-up、`/ready`）
- `D:\project\AI-QA-Assistant-agent-memory\agent\agent\api\chat_routes.py`（仅删除旧公开 reset route）
- 新建 `D:\project\AI-QA-Assistant-agent-memory\agent\agent\api\internal_memory_routes.py`
- 对应 internal route、token dependency、FastAPI dependency override 与公开 route 拒绝内部字段的 tests
- `D:\project\AI-QA-Assistant-agent-memory\agent\docs\API_CONTRACT.md`（仅内部 endpoint 说明）

禁止修改 `schemas/chat.py`、`config/settings.py`、`agent.py`、`orchestration/orchestrator.py`、
`runtime/runner.py`、`runtime/lifecycle.py`、`tools/executor.py`、`deep_research/**` 或 Web 文件；DTO/
配置属于 `04`，Resolver/Pipeline 属于 `05`/`06`，Planner 属于 `07`。

## 分阶段端点行为与开关门禁

`04a` 必须先完成 transport/auth/reset，不能假装 05、06、07 已完成。所有部署环境在 `07`
审查通过前都必须保持 Web `PERSISTENT_MEMORY_ENABLED=false`，因此 BFF 不会把真实浏览器流量
送入私有 endpoint；Agent 开关只能在 endpoint contract test 的局部 override 中开启。

在 `04a` 完成后的固定中间状态：

1. `POST /api/internal/chat` 在 Agent persistent 开关关闭时仍返回固定 409
   `persistent_memory_disabled`。测试 override 开关后，handler 只复用共享 `get_agent()` 执行现有
   Chat，并返回既定 `InternalChatResponse` 与空 `fact_proposals`；它只做 DTO/token 边界校验，
   不解析或注入 `memory_context`，不生成 Fact。
2. `POST /api/internal/memory/compaction-plan` 在 `07` 前固定返回
   `{ "should_compact": false }`，不读写数据库、不生成 Snapshot。该稳定 no-op 使 Web 在测试中
   可以安全调用；`07` 是唯一可替换为 `CompactionPlanner` 的单元。
3. `POST /api/internal/memory/reset-short-window` 在 `04a` 即完整可用：只调用旧
   `ConversationMemory.clear(chat_id)`，不读写 Snapshot/Fact。

`06` 是唯一可把 internal chat handler 接到 `ContextResolver`、Prompt/Recall 的单元；完成前不得
声称 persistent context 已生效。`07` 审查通过且 Web/Agent 两侧开关配置一致后，才允许在集成
环境开启 persistent Memory；`13` 仍控制任何发布环境的启用顺序。

## 鉴权

所有 `/api/internal/*` endpoint 要求 header：

```text
X-Agent-Internal-Token: <AGENT_INTERNAL_TOKEN>
Content-Type: application/json
```

Agent 以常量时间比较 token；缺失或不匹配一律返回 403，无响应差异。Web 从环境读取 token，浏览器永不接触。私有端点在反向代理/防火墙层只允许 BFF 网络身份；token 不是唯一网络边界。

本轮适配不引入 `feat/permission-hardening` 的 Bearer 鉴权。若未来要把该分支纳入，必须新开契约施工单；不得在本施工单中静默替换、复用或放宽 `X-Agent-Internal-Token`。

在冻结 runtime `5955cd0` 上，internal router 必须通过 `agent.api.chat_routes.get_agent()` 取得
`ApplicationContainer` 中的共享 Agent。不得创建第二个 Agent、第二个 `ConversationMemory` 或自行管理 lifespan。

## Endpoint 1：私有聊天

```text
POST /api/internal/chat
```

请求：`InternalChatRequest`，包含现有 ChatRequest 字段与必填 `memory_context`。`memory_context` 使用 `04` 的 actor/chat/revision/current message/snapshot/facts/tail DTO。BFF 必须在用户消息落库后构造它。路由选择固定：仅 authenticated actor 且 Web `PERSISTENT_MEMORY_ENABLED=true` 时调用本端点；匿名用户或 Web 开关关闭时调用公开 `/api/chat`，不得发送占位 `memory_context` 来假装私有调用。若 Agent 开关关闭，本端点固定返回 `409 { "code": "persistent_memory_disabled" }`，BFF 记录配置错误后只回退一次公开 `/api/chat`。

响应：

```json
{
  "response": { "trace_id": "...", "status": "success", "answer": "...", "message": "", "citations": [] },
  "memory_decision": { "fact_proposals": [] }
}
```

`response` 必须与公开 ChatResponse 值等价；`memory_decision` 不能转发至浏览器。为稳定跨层 schema，字段在 01--08 保留但 `fact_proposals` 必须为空数组。`09-Agent` 与 `09-Web` 在 `09a-Web` 合同之后启用 proposal lifecycle，才另行规定显式触发、`source_message_id` 校验、BFF 写入 PROPOSED Fact 和浏览器读取方式；在此之前 BFF 不得因该字段写 Fact。

提议、持久化、确认和撤销只在 `09a-Web`、`09-Agent`、`09-Web` 开始后实现。本 endpoint 的字段保留是为了维持冻结契约，而不是授权提前施工。

## Endpoint 2：压缩计划

```text
POST /api/internal/memory/compaction-plan
```

请求必填：可信 actor、chat ID、revision、active Snapshot（可为 null）、当前已持久化 messages（包含助手消息）、`tail_size`、`min_coverable_messages`、`soft_token_budget`。BFF 只在 `02b` 的 `ASSISTANT_PERSISTED` 后调用。

响应：

```json
{ "should_compact": false }
```

或：

```json
{
  "should_compact": true,
  "expected_active_snapshot": { "id": "...", "version": 2, "revision": 1 },
  "new_snapshot": {
    "covered_from_sequence": 1,
    "covered_to_sequence": 24,
    "covered_from_message_id": "...",
    "covered_to_message_id": "...",
    "summary": "..."
  }
}
```

Agent 不写数据库；Web Repository 以 expected snapshot ID/version/status 执行乐观归档和新建。HTTP timeout、403、5xx、无效 schema 均视为“不压缩”，不能回滚助手消息。

## Endpoint 3：兼容短窗重置

```text
POST /api/internal/memory/reset-short-window
```

请求固定为：

```json
{ "chat_id": "..." }
```

响应固定为：

```json
{ "status": "ok" }
```

BFF 仅在编辑、重生成或删除 chat 的数据库事务提交成功后调用。Agent 只执行旧 `ConversationMemory.clear(chat_id)`，不读写 Snapshot/Fact。该端点替代并删除现有无 token 的 `DELETE /api/chat/memory/{session_id}`；缺 token 得到 403。reset 失败只影响关闭持久 Memory 时的短窗兼容体验，不回滚 Web 的 edit/delete 事务。

## 实施与测试

- Agent 新建 internal router/dependency，删除公开 reset route，公开 `/api/chat` 不接受 `memory_context`。在 5955 上，`app.py` 保留 `ApplicationContainer`、warmup 和 `/ready`，只额外执行 `app.include_router(internal_memory_router, prefix="/api/internal")`；三个端点必须严格遵守上述阶段性语义。
- 在 Agent worktree 为缺 token、错误 token、外部 public 请求传 memory 字段、DTO version 不匹配、开关关闭 409 和 `get_agent()` dependency override 增加 contract tests。不得构造新的 Agent。
- 审查 Web 已有的 server-only `agentInternalClient.ts`、5 秒超时、`isPersistentMemoryEnabled()`、5xx 处理及 `persistent_memory_disabled` 单次公开回退；本单元不修改 Web 实现。
- 更新内部 API 文档，并明确 `ChatResponse` 不变。

## 完成标准

全仓只存在这三条 Memory 私有调用路径；全文搜索不得再发现无 token reset route、response header 或全局 MemoryDecision 传递方案。交接 endpoint contract version 给所有后续单元。
