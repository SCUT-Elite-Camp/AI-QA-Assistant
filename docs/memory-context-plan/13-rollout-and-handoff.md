# 13 发布、回滚与团队交接

## 目标

将已通过测试的 Persistent Memory 以可关闭、可观测、可回滚方式交付；明确团队如何从本地施工文档转为可 Review 的实现 PR。

前置：`12`。负责人：Web/Agent 集成人与负责人。

## 发布顺序

1. 所有环境默认：三个开关均为 false。
2. 测试环境仅开启 `PERSISTENT_MEMORY_ENABLED`，Fact 开关仍关闭；验证 Snapshot/Tail 与降级指标。
3. 测试环境开启 `SESSION_FACT_ENABLED`，执行确认/撤销/删除/跨用户验收。
4. 小范围测试用户启用两个功能；每日检查 compaction failure/conflict、fallback、权限拒绝与 Prompt 长度指标。
5. 达到验收门槛后才扩大；`MEMORY_CACHE_ENABLED` 始终 false。本项目没有 Redis 施工单时不得启用它。

## 回滚

- 普通故障：关闭 `PERSISTENT_MEMORY_ENABLED`，恢复短窗聊天；保留历史 Snapshot/Fact，不删除数据。
- Fact 交互故障：只关闭 `SESSION_FACT_ENABLED`；不让未确认 proposal 自动转 confirmed。
- 权限/泄露疑虑：立即关闭两个功能、阻断 Fact API、保留必要脱敏审计，按团队安全流程处理。
- 迁移已执行时不得用手工删表回滚；需要经 Review 的 forward migration 或受控备份恢复。

## 交接与 PR 规则

- Web 实现走 `web-dev`，Agent 实现走 `agent-dev`；禁止直接 push `dev/main`。
- 一个 PR 只覆盖连续且同 owner 的施工单；跨层 DTO 首先提交契约 PR/评审记录。
- 每个 PR 描述必须列明本目录中的施工单编号、变更路径、开关默认值、测试结果、未验证项与回滚动作。
- 本目录目前被忽略；实现前由团队将认可的契约摘要迁入可提交的 `docs/` 或 Confluence。忽略的本地草案不能作为唯一团队事实来源。

## 最终交付物

1. Web migration 与 Repository/route/UI 实现；
2. Agent DTO、Resolver、Policy、Planner 与 Prompt 接线；
3. 更新的内部/公开 API 契约；
4. 测试报告与可复现验收记录；
5. 开关、指标、故障降级、回滚 Runbook；
6. 明确说明 Redis、USER Fact、自动确认仍未实现。

## 完成条件

所有 `12` 门槛通过，开关默认安全，跨层 owner 已签字或 PR approve，且有实际可复现的关闭/回滚演练记录。否则项目仍处于实施中，不得宣称持久 Memory 已完整上线。
