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

## 交接与单线协作规则

- Web 实现继续在 `web-dev`；Agent Memory 集成只在以 `5955cd0` 为冻结代码祖先的 `agent-dev-infra` 工作线进行（允许先叠加 docs-only 同步提交）。禁止直接 push `dev/main`，也禁止从旧 `web-dev` 整体 cherry-pick Agent Memory 提交。
- Agent 热点文件采用写锁：同一时段只有一位集成人可修改 `agent.py`、`orchestrator.py`、`runner.py`、`app.py`、`chat_routes.py`、schemas/config 与内部路由。其他同学通过独立文件、测试建议或向持锁人提交补丁参与；锁交接须记录基线 hash 和未提交文件。
- 一个提交/PR 只覆盖连续且同 owner 的施工单；跨层 DTO 先维护契约评审记录。Agent 迁移按 `06b` 的文件矩阵人工合并，保留 `runtime/lifecycle.py`、`tools/executor.py` 与 `deep_research/**`。
- 本目录是已追踪的团队施工文档，必须与实现一起评审；更新后同步到 Agent Memory 工作目录或在交接中写明其来源 commit。不得把本目录当作 `.gitignore` 中的个人草稿。
- 每个提交/PR 描述必须列明施工单编号、变更路径、开关默认值、测试结果、未验证项、回滚动作，以及 Chat/Deep Research 未耦合的检查结果。

## 最终交付物

1. Web migration 与 Repository/route/UI 实现；
2. Agent DTO、Resolver、Policy、Planner 与 Prompt 接线；
3. 更新的内部/公开 API 契约；
4. 测试报告与可复现验收记录；
5. 开关、指标、故障降级、回滚 Runbook；
6. 明确说明 Redis、USER Fact、自动确认仍未实现。

## 完成条件

所有 `12` 门槛通过，开关默认安全，跨层 owner 已签字或 PR approve，且有实际可复现的关闭/回滚演练记录。否则项目仍处于实施中，不得宣称持久 Memory 已完整上线。
