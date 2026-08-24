# 09 SESSION Fact 生命周期导航页（不可执行）

本文件只说明业务目标，不能作为 `<XX>` 输入执行。原先的跨层 `09` 已拆为两个唯一工作区的原子单元，
以消除“在 Agent 工作区执行 Web route”与并行修改热点文件的风险：

1. `09a-Web`：[`09a-fact-idempotency-contract.md`](09a-fact-idempotency-contract.md)，冻结并实现
   Repository/HTTP 合同。
2. `09-Agent`：[`09-agent-fact-proposal-and-recall.md`](09-agent-fact-proposal-and-recall.md)，只生成
   严格受限的候选并处理确定性回忆。
3. `09-Web`：[`09-web-fact-lifecycle.md`](09-web-fact-lifecycle.md)，只在 Web BFF 持久化候选、实现
   Fact routes 与手动保存。

固定顺序是 `09a-Web → 审查 → 09-Agent → 审查 → 09-Web → 审查`。首版仅支持
`SESSION` scope、`GOAL`、`PREFERENCE`、`PLAN_CONSTRAINT`；提议永远不是确认，只有同 revision、
已确认且未过期的 Fact 可进入 ContextArtifact。`10-Web` 只在三者均通过后开始。
