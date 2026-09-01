# 09-Agent 受控 Fact 候选与确定性回忆

## 目标与当前状态

只在用户使用明确命令时，由 Agent 生成**候选** Fact；Agent 不写 MySQL、不确认、不撤销、不计算
过期时间，也不创建浏览器 API。`04`--`08` 中的 `fact_proposals` 固定为空数组；本单元是唯一可以
改变该事实的 Agent 单元。

前置：`09a-Web` 已审查通过，`04`、`05`、`06`、`07`、`08` 已完成。后续：`09-Web`、`10-Web`、
`11-Agent`、`12`。负责人：Agent。

## 施工位置与允许修改范围

```text
唯一工作区：D:\project\AI-QA-Assistant-agent-memory
唯一分支：agent-dev-infra
```

允许修改：

- `agent/agent/agent.py`
- `agent/agent/config/settings.py`（只新增 `SESSION_FACT_ENABLED`，默认 false）
- 新建 `agent/agent/memory/fact_proposal_policy.py`
- 仅在需要接入该纯 policy 时修改 `agent/agent/memory/memory_response_policy.py`
- `agent/agent/schemas/chat.py`（仅保持 09a 的兼容 envelope；禁止改公开 ChatResponse）
- `agent/tests/unit/test_fact_proposal_policy.py`
- `agent/tests/unit/test_memory_response_policy.py`
- `agent/tests/unit/test_agent.py` 与直接相关 integration tests
- `agent/docs/API_CONTRACT.md`（仅内部 decision 说明）
- `agent/.env.example`（只增加 `SESSION_FACT_ENABLED=false` 占位）

禁止修改 `app.py`、`api/chat_routes.py`、`api/internal_memory_routes.py`、`runtime/**`、
`orchestration/**`、`tools/**`、`deep_research/**`、Web 文件、数据库 schema 或任何公开 HTTP 响应。
若接线需要上述热点文件，停止并报告给集成人；不得绕过写锁。

## 输入、输出与确定性规则

### 允许产生候选的唯一命令

候选识别是纯函数，禁止调用 LLM、RAG、工具或意图模型。只接受完整 user query（Unicode NFC、trim 后）
匹配以下大小写不敏感命令；`<value>` 不能为空，最多 500 Unicode code points：

| category | 中文命令 | 英文命令 |
| --- | --- | --- |
| `GOAL` | `记住目标：<value>` 或 `请记住目标：<value>` | `remember goal: <value>` |
| `PREFERENCE` | `记住偏好：<value>` 或 `请记住偏好：<value>` | `remember preference: <value>` |
| `PLAN_CONSTRAINT` | `记住计划约束：<value>` 或 `请记住计划约束：<value>` | `remember plan constraint: <value>` |

全角冒号 `：` 与半角冒号 `:` 等价；命令外的前缀/后缀、含糊的“请记住我喜欢……”和任何模型/工具
输出都不产生候选。用户仍可在 `10-Web` 的手动入口保存任意自己的非敏感历史消息。该保守语法是首版
避免无感采集的唯一准则，未来若扩展自然语言识别必须另开施工单。

候选的唯一输出严格为：

```json
{
  "category": "GOAL | PREFERENCE | PLAN_CONSTRAINT",
  "value": "NFC + trim + whitespace collapsed value",
  "source_message_id": "memory_context.current_message_id",
  "expires_at": null
}
```

只有以下条件同时满足才允许输出一项候选：`PERSISTENT_MEMORY_ENABLED=true`、
`SESSION_FACT_ENABLED=true`、trusted memory context 的 actor 已认证、
当前 source 是 context 的 current persisted user message，且 `isSensitiveMemoryValue(value)` 为 false。
任一条件不满足、policy 抛错或 value 敏感时返回空数组且不记录 value。每轮最多一项，禁止从历史 Tail、
Snapshot、Fact、assistant answer、citation 或 tool output 推导候选。

### 确定性回忆

仅在 `ContextArtifact` 已由 `05` 提供可见 Fact 时，以下精确 query 触发既有 MemoryResponsePolicy：

```text
我记住了什么？
我之前确认的记忆是什么？
what have you remembered?
what are my confirmed memories?
```

命中且有 Fact：按 `createdAt ASC, id ASC` 返回简短、确定性列表，只含 category/value，不含 ID、
source、expiry 或 Snapshot。命中但无可见 Fact：返回固定空结果。其余 query 永不绕过 LLM/RAG；
Fact 不能产生 RAG citation。此 policy 必须继续防止 prompt injection，把 Fact 文本作为 data 而非 instruction。

## 有序实施步骤

1. 在 Settings 与 `agent/.env.example` 新增 `SESSION_FACT_ENABLED=false`；只允许测试通过环境/monkeypatch
   显式打开，不能默认随 persistent 开关打开。
2. 新建无副作用的 `fact_proposal_policy.py`，以表驱动用例实现命令解析、NFC/空白规范化、长度限制和
   敏感过滤；不得复制或改写 `07` 的敏感规则。
3. 在 `Agent.chat_with_memory()` 的成功 decision 组装点调用该 policy。候选只进入内部
   `MemoryDecision.fact_proposals`，公开 `ChatResponse` 字段保持不变。
4. 确认 `FactProposal.expires_at` 保留且恒为 null；不允许 Agent 计算 30/90 天或 proposal key。
5. 将回忆触发限定为上述精确 query，复用已解析的 visible confirmed Facts；普通问答、无 Fact、禁用
   开关和 policy 异常均按既有路径安全降级。
6. 更新内部 API 文档，说明 Web 是唯一持久化方，Agent proposal 不是已保存/已确认 Fact。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant-agent-memory\agent
..\.venv\Scripts\python.exe -m pytest tests/unit/test_fact_proposal_policy.py tests/unit/test_memory_response_policy.py tests/unit/test_agent.py tests/integration/test_internal_memory_routes.py
..\.venv\Scripts\python.exe scripts/check_contract.py
```

必须覆盖全部中文/英文命令、非命令、空值、超长值、敏感值、匿名/关闭 gate、source ID、`expires_at=null`、
一轮最多一项、显式回忆命中/空结果及普通 query 不触发。完成条件是命令成功、公开 ChatResponse 无 diff、
不导入/创建 Deep Research。

停止并报告：需要改变 09a envelope、需要访问数据库、需要 LLM 自由抽取、需要修改 Agent 热点路由/Runtime，
或 `09a-Web` 尚未通过。交接给 `09-Web` 的唯一输入是已验证的内部 `MemoryDecision.fact_proposals`。
