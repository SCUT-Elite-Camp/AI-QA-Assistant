# Unit 13 发布就绪审查与交接（阶段 A）

> 审查日期：2026-08-24  
> 范围：仅本地工作区、已提交代码与 Unit 12 证据。未执行 push、部署、环境开关变更、灰度、生产查询、数据库操作或回滚操作。  
> 阶段 A 结论：**FAIL — 不得请求或执行阶段 B 灰度。**

## 1. 审查输入、代码基线与工作区状态

| 项目 | 本地检查结果 | 结论 |
| --- | --- | --- |
| Web 基线 | `web-dev` HEAD=`c9d8129af017372db8562373c1d783993155ab97`；本地 `origin/web-dev`=`49efbfacd10afb5aea0e5988de2d01bdbcee5f55`；`git status -sb` 为 `ahead 7`，无未提交文件 | 源码/文档尚未推送，不能声称远程 PR 已可审查。 |
| Agent 基线 | `agent-dev-infra` HEAD=`4b3f333e213d0a60a78b32ba0a3781bb0aab3343`；本地 `origin/agent-dev-infra`=`d381d9e8515ade1fbe7c0c60220e2540901fff45`；相对本地 remote 为 `ahead 2` | 源码尚未推送，不能声称远程 PR 已可审查。 |
| 冻结 Runtime 基线 | `git merge-base --is-ancestor 5955cd0c2a60fe439d4206befb42307a271aef86 HEAD` 退出 `0` | Agent Memory 提交仍以冻结 Runtime 为祖先。 |
| Agent 工作区 | `M data-persistence/data/chat_history.db` | 这是本地 smoke 服务运行生成的数据文件；未纳入代码/证据提交，也不能作为干净的发布工作树。不得删除或提交它，需由数据所有者清理或保留。 |
| Unit 12 输入 | [12-acceptance-report.md](12-acceptance-report.md) 记录 Web 17 files / 108 tests 通过、Agent 308 passed，以及已完成的本地 smoke | 可作为阶段 A 的测试证据；不代表真实环境或生产质量。 |

本单元没有修改 Agent 源码或其热点文件。Agent 写锁 holder 在当前受跟踪文档、提交消息和本地 Git 元数据中均未找到可验证记录；发布/回滚前必须由负责人明确写入 holder、锁定文件和释放条件。

## 2. PR、owner 与交接责任

| 必需项 | 当前证据 | 状态 |
| --- | --- | --- |
| Web PR 与 owner review | 本地分支领先 `origin/web-dev` 7 个提交；本单元禁止 remote Git 操作，且没有本地 PR/approve 元数据 | **缺失** |
| Agent PR 与 owner review | 本地分支领先 `origin/agent-dev-infra` 2 个提交；没有本地 PR/approve 元数据 | **缺失** |
| 发布负责人 | 未在输入中指定 | **缺失** |
| 回滚负责人 | 未在输入中指定 | **缺失** |
| Agent 写锁 holder / 释放条件 | 未在输入中指定或受跟踪记录 | **缺失** |

因此不得直接 push `dev` 或 `main`，也不得创建灰度环境。本报告不虚构 PR 链接、审批人、负责人或外部环境信息。

## 3. 默认开关、依赖与安全边界

| 检查项 | 代码/测试证据 | 结论 |
| --- | --- | --- |
| Persistent 默认关闭 | Agent `agent-dev-infra@4b3f333:agent/agent/config/settings.py:73` 默认 `false`；[memoryFeatureFlags.ts](../../../web/server/utils/memoryFeatureFlags.ts) 仅显式真值启用 | 通过。 |
| Session Fact 默认关闭 | 同上，`SESSION_FACT_ENABLED` 默认 `false`；Web feature-flag 回归验证未知值/`0` 为关闭 | 通过。 |
| Cache / Redis | 两端 `MEMORY_CACHE_ENABLED=false`；真值会固定报 `memory_cache_not_supported`；环境示例没有 Redis 配置 | 通过；本版本无 Redis 依赖。 |
| 内部 token | Agent internal route 以常数时间比较 `X-Agent-Internal-Token`；缺失/无效均为 403；Unit 12 Agent 回归覆盖 | 通过。 |
| 公共兼容性 | 公共 `ChatRequest` 拒绝 `memory_context`，`ChatResponse` 不含 Memory；internal response 才携带 `memory_decision` | 通过。 |
| Chat / Deep Research 隔离 | Agent 生产 lifespan 回归会在 Chat/Memory 端点导入 `deep_research` 时失败；Unit 12 已通过 | 通过。 |
| RAG citation 边界 | Memory recall 是 deterministic internal decision；Unit 12 exact-recall smoke 与公共响应合同未将 Fact 作为 citation | 通过。 |

受跟踪环境示例只包含空 token 占位和三个关闭的默认值：
Agent `agent-dev-infra@4b3f333:agent/.env.example` 与 [web/.env.example](../../../web/.env.example)。本审查不读取或记录任何实际 `.env`、Cookie、token 或部署秘密。

## 4. 观测、告警与隐私边界

| 观察项 | 有限指标/事件证据 | 发布观察动作 |
| --- | --- | --- |
| compaction failed / conflict | `memory_compaction` 仅允许 `skipped|planned|conflict|failed`；Web `memory.compaction` 计数和 Agent 无正文 event 均已回归 | 若 `conflict` 或 `failed` 持续出现，先关闭 persistent，保留数据库记录供受控排查。 |
| internal fallback | Web 仅记录有限的 `agent_disabled|internal_error|context_error`；409 回退一次的回归已通过 | 观察 `agent_disabled` 与 `internal_error`，持续异常先关闭 persistent。 |
| 403 / 409 | Agent internal-route 回归覆盖相同 403 与 persistent-disabled 409；Web HTTP metrics 保留 endpoint 的 status-code 计数 | 403 激增检查 BFF/Agent token 配置；409 按预期触发一次公开降级。 |
| Fact 操作失败 | `memory_fact` 仅允许 action/outcome 枚举，包含 `failed`、`sensitive`、`disabled` | 观察 `failed`；安全疑虑立即关闭 Fact gate。 |
| prompt length | `MEMORY_MODEL_HISTORY_MAX_CHARS=6000` 提供输入上界，Resolver 按该值截断 | **缺失显式、无正文的 prompt-length 指标。** 当前只有上界，不足以满足发布期告警观察要求。 |

Web 的 [metrics.ts](../../../web/server/utils/metrics.ts) 和 [logger.ts](../../../web/server/utils/logger.ts)，以及 Agent `agent-dev-infra@4b3f333:agent/agent/memory/memory_observability.py` 都只接收有限 label/数值；Unit 12 回归验证日志 payload 不含 query、Fact value、Snapshot、Tail、message/chat ID、prompt 或 token。不得通过扩展日志正文来弥补 prompt-length 指标缺失。

## 5. 回滚 Runbook（未执行外部操作）

本节是经现有回归验证的桌面演练，不是环境变更。实际执行需要阶段 B 的单独授权及已指定的回滚负责人。

1. **Persistent 回滚。** 在获授权环境将 `PERSISTENT_MEMORY_ENABLED` 设为 `false` 后，Agent private chat 返回固定 409，BFF 只降级一次到公开/短窗路径；不删除或改写已有 Snapshot、Tail、Fact。依据：Agent internal-route 和 Web internal-client 回归。
2. **Fact 回滚。** 在获授权环境将 `SESSION_FACT_ENABLED` 设为 `false` 后，禁止 proposal/confirm/revoke 与 deterministic Fact recall；不得自动确认既有 proposal。Persistent Snapshot/Tail 可以依照其独立 gate 保持可用。
3. **安全回滚。** 若出现权限、隐私或日志疑虑，同时关闭 persistent 与 session fact，阻断 Fact API；保留受控审计所需的无正文指标，不输出 Fact 内容。
4. **迁移回滚。** 已执行 migration 只能走经 review 的 forward migration，或由数据库负责人从受控备份恢复；严禁手工删表、删行或通过回滚代码破坏 Snapshot/Fact 记录。

该演练没有改变任何实际环境开关、没有连接 Redis、没有执行数据库命令，也没有处理真实秘密。`memory_cache_not_supported` 的 fail-closed 回归是本版本“不得启用 Redis”的验证。

## 6. 明确未实现与不可作出的声明

- Redis / `MEMORY_CACHE_ENABLED` 支持；
- 跨会话 `USER` Fact；
- 自动确认、自由自然语言 Fact 抽取或自动保存敏感信息；
- 生产性能、模型回答质量、RAG 检索质量或 SLA；
- 多账号真实灰度、部署、生产观测和外部回滚。

本地 single-account smoke、mock/integration test 和本报告都不能被表述为已上线或已完成生产灰度。

## 7. 阶段 A 判定与交接

**判定：FAIL。** Unit 12 的自动化与本地 smoke 证据可用，但以下阻断项尚未满足：

1. Web 与 Agent 的当前提交均未推送到各自 remote tracking ref，且没有可验证 PR/owner approval；
2. 未指定发布负责人、回滚负责人、Agent 写锁 holder 与释放条件；
3. Agent 工作区包含未提交的 `data-persistence/data/chat_history.db`；
4. 没有显式、无正文的 prompt-length 发布观测指标，只有 `6000` 字符上界。

交接给负责人：在独立的相应原子单元修复第 4 项并审查；由负责人处理第 1--3 项。只有再次审查本报告为 PASS 后，才可请求包含环境、命令范围、开关阶段、灰度范围、观察时长、负责人和回滚阈值的阶段 B 明确授权。

## 8. 阶段 A 补充更新（2026-08-24）

本补充记录发生在第 7 节结论之后；它不会将阶段 A 改写为 PASS。

| 项目 | 复核结果 | 结论 |
| --- | --- | --- |
| Web remote ref | `web-dev` 远程分支已包含截至 `97723ec` 的 Web Memory 提交。 | 已消除“未推送”风险。 |
| Agent remote ref | `agent-dev-infra` 已推送至 `4c219b5`。 | 已消除“未推送”风险。 |
| 远程 PR / review | 浏览器已验证 Agent PR [#25](https://github.com/SCUT-Elite-Camp/AI-QA-Assistant/pull/25) 为 open，base=`agent-dev`、head=`agent-dev-infra`，并包含 `4c219b5`；5 位 CODEOWNERS 均为 pending review。Web compare 页面可创建 `dev...web-dev` PR，但尚未提交。GitHub connector 创建 Web PR 返回 `403 Resource not accessible by integration`。 | **仍缺失已创建的 Web PR 与独立 owner approval。** 不得伪造或自我批准。 |
| Prompt length | `agent-dev-infra@4c219b5:agent/agent/agent.py` 只在 trusted persistent Context 已实际得到 Runner 结果后发出 `memory_prompt {model_history_chars}`；`memory_observability.py` 仅接收非负整数。`agent/docs/API_CONTRACT.md` 已同步合同。 | 已消除“只有 6000 上界、没有无正文指标”风险。 |
| Prompt length 回归 | `..\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_internal_memory_contract.py tests/unit/test_context_resolver.py tests/unit/test_compaction_planner.py tests/unit/test_fact_proposal_policy.py tests/unit/test_memory_observability.py tests/integration/test_internal_memory_routes.py -q`：**82 passed**；`..\\.venv\\Scripts\\python.exe scripts/check_contract.py`：通过。 | 事件包含实际 Runner 路径、exact-recall 不发事件、负数拒绝及无正文 payload 回归。 |
| Agent 本地 DB | `data-persistence/data/chat_history.db` 仍是唯一未提交修改。端口 8000 没有监听者，已确认无运行服务占用；但尚未获数据所有者明确授权丢弃其中 smoke 记录。 | **仍阻断干净发布工作树。** 必须在确认“可丢弃”或先受控备份后，由持有人清理。 |

因此，当前仍为 **FAIL**。剩余不可由自动化代填的阻断项仅为：

1. 提交已准备好的 `dev...web-dev` PR，并完成独立的 CODEOWNERS/owner 审查；Agent PR [#25](https://github.com/SCUT-Elite-Camp/AI-QA-Assistant/pull/25) 已包含 `4c219b5`，但 5 个 owner review 均仍 pending；
2. 发布负责人、回滚负责人、Agent 写锁 holder，以及持锁的文件范围和释放条件；
3. Agent 本地 smoke 数据库的明确保留/备份/丢弃决定，之后得到干净工作树。

## 9. 负责人、PR 与本地数据最终更新（2026-08-24）

以下内容由发布持有人明确确认，不是自动推断：

| 必需项 | 已确认的责任与边界 | 状态 |
| --- | --- | --- |
| Web PR | [#26](https://github.com/SCUT-Elite-Camp/AI-QA-Assistant/pull/26) 已创建，base=`dev`、head=`web-dev`。PR 本身声明在独立 CODEOWNERS review 前不得 merge/deploy。 | 已满足“可审查 PR”前置；**审批仍待完成**。 |
| Agent PR | [#25](https://github.com/SCUT-Elite-Camp/AI-QA-Assistant/pull/25) 为 open，base=`agent-dev`、head=`agent-dev-infra`，并包含 `4c219b5`。 | 已满足“可审查 PR”前置；**审批仍待完成**。 |
| 发布负责人 | `songsuijie`（当前发布持有人）。 | 已指定。 |
| 回滚负责人 | `songsuijie`（当前发布持有人）。 | 已指定。 |
| Agent 写锁 | `songsuijie` 是口头约定的唯一 holder；范围为 `agent-dev-infra` 的 Agent Memory 改动。它不是仓库强制锁。holder 在完成独立 PR review 并明确交接/释放 Agent 改动控制权后释放。 | 已指定且已说明非强制性质。 |
| Agent 本地运行 DB | 按持有人授权，停止确认属于 `D:\\project\\AI-QA-Assistant-agent-memory` 的本地 `app.py` 后，确认端口 8000 已释放，并将 `data-persistence/data/chat_history.db` 还原到提交版本；未上传或保留 smoke 聊天记录。 | 已消除脏工作树风险。 |

此后阶段 A 的唯一阻断项是：两个 PR 均须得到独立的 CODEOWNERS/owner approval。当前持有人不得对自己创建的 PR 自行审批，也不得在审批前 merge、部署或开启 persistent/Fact 环境开关。
