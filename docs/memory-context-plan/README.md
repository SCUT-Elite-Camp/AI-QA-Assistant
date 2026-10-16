# Memory 计划与契约索引

[返回文档导航](../README.md)

本目录保留编号、原子单元和夹具位置。实施或审查前先读 [00 施工总控书](00-execution-guide.md)，其中的状态和工作区限制决定各单元是否可执行。历史工作区路径不能直接当作当前机器的运行配置。

| 阶段 | 文档 |
| --- | --- |
| 身份、消息生命周期 | [01 身份](01-web-identity-and-access.md)、[02 消息顺序](02-message-order-and-lifecycle.md)、[02a 迁移](02a-sequence-migration-runbook.md)、[02b 完成状态机](02b-stream-completion-state-machine.md) |
| Schema、内部接口与上下文 | [03 Schema](03-memory-schema-and-migration.md)、[04 契约](04-internal-memory-contract.md)、[04a 端点](04a-internal-endpoint-specification.md)、[05 Snapshot/Tail](05-snapshot-tail-resolution.md) |
| Agent、压缩与删除 | [06 Prompt/Recall](06-agent-prompt-and-recall.md)、[06a 基线](06a-agent-baseline-lock.md)、[06b 核对](06b-agent-infra-5955-reconciliation.md)、[07 压缩](07-post-turn-compaction.md)、[08 历史变更](08-history-mutation-and-deletion.md) |
| Fact 生命周期 | [09 总导航](09-session-fact-lifecycle.md)、[09 Agent](09-agent-fact-proposal-and-recall.md)、[09 Web](09-web-fact-lifecycle.md)、[09a 幂等](09a-fact-idempotency-contract.md)、[10 Web 体验](10-fact-web-experience.md) |
| 安全、开关与可观测性 | [11 总导航](11-security-observability-and-flags.md)、[11 Agent](11-agent-flags-security-observability.md)、[11 Web](11-web-flags-security-observability.md) |
| 测试与交接 | [12 验收](12-test-and-acceptance.md)、[12a Web Harness](12a-web-test-harness.md)、[13 推出与交接](13-rollout-and-handoff.md) |

`09` 和 `11` 的总导航页不能作为施工单执行。`evidence/fixtures/` 是前端契约测试直接读取的共享 JSON 夹具。当前来源权限及历史 Memory 释放规则仍以[访问架构](../access-evidence/access-evidence-architecture.md)为准。
