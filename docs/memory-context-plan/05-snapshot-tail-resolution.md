# 05 Snapshot + Tail 解析为 ContextArtifact

## 目标

将 Web 提供的同 revision Snapshot、确认 Fact 与未覆盖 Tail 规则式组装为 Agent 可消费的 `ContextArtifact`。本单元不落库、不压缩、不调用 LLM。

前置：`04`、`04a`。负责人：Agent。后续依赖：`06`、`07`。

施工位置：`D:\project\AI-QA-Assistant-agent-memory`（`agent-dev-infra`）。Web 已有的
`memory_context` 构造只作审查证据；本单元不修改 `D:\project\AI-QA-Assistant`。

## 目标行为

当 `PERSISTENT_MEMORY_ENABLED=false`、请求无可信 `memory_context` 或 actor 未认证时，保持原 `ConversationMemory` 短窗路径。当开关打开时：

1. 只接受 `snapshot.history_revision == context.revision`。
2. 只保留 `sequence > snapshot.covered_to_sequence` 的 Tail；无 Snapshot 时 Tail 从当前 revision 的第一条开始。
3. Tail 只接受 `user` 和 `assistant` role、非空文本、同 revision、`sequence > covered_to_sequence` 的消息；按 sequence 升序排列后只保留最新 8 条。`02b` 已保证错误占位和半截回答不落库。当前用户消息 ID 等于 `context.current_message_id` 时必须从 Tail 剔除，因为 Runner 会单独追加 query。
4. `memoryBrief = CONFIRMED 且未过期的 SESSION Facts + ACTIVE snapshot.summary`；按固定模板、固定最大长度生成，不调用模型。
5. `modelHistory = memory system message + Tail`。memory system message 声明其内容是用户上下文，不是可执行指令；不得覆盖系统安全/证据约束。

## 允许修改范围

- 新建 `D:\project\AI-QA-Assistant-agent-memory\agent\agent\memory\persistent_models.py`
- 新建 `D:\project\AI-QA-Assistant-agent-memory\agent\agent\memory\context_resolver.py`
- 修改 `D:\project\AI-QA-Assistant-agent-memory\agent\agent\config\settings.py`，仅增加配置读取
- 新建 `D:\project\AI-QA-Assistant-agent-memory\agent\tests\unit\test_context_resolver.py`

`ContextResolver` 是纯函数式 Chat Memory 组件：不得导入 `ApplicationContainer`、`deep_research`、数据库、HTTP client 或 LLM。5955 的共享 Agent 生命周期不改变本单元的输入输出；internal endpoint 接线属于 `04a`，最终 Prompt 接入属于 `06`；`06b` 只记录迁移前核对，不含代码接线。

固定默认配置：`PERSISTENT_MEMORY_ENABLED=false`、`MEMORY_TAIL_MESSAGES=8`、`MEMORY_BRIEF_MAX_CHARS=1200`、`MEMORY_MODEL_HISTORY_MAX_CHARS=6000`。配置必须有合法范围，不能依赖硬编码常量。

## 必测场景

- 无 Snapshot、有效 Snapshot、过期/错误 revision Snapshot。
- Tail 边界为 `covered_to_sequence + 1`；顺序稳定；当前 query 不出现两次。
- PROPOSED/REVOKED/过期 Fact 不进入 brief。
- Fact/Snapshot 文本带“忽略系统指令”等 prompt injection 时，作为数据被隔离而非执行。
- 开关关闭时旧 `ConversationMemory` 行为不变。

## 完成与交接

输出 `ContextArtifact` 及 unit tests 给 `06`；不可在本单元碰 Runner 热点、`ApplicationContainer` 或数据库。任何摘要质量问题先以有界裁剪和结构化文本解决，不允许私自引入 LLM 压缩。`ContextArtifact` 只能服务 Chat，不能进入 Deep Research Graph State。
