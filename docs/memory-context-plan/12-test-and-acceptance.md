# 12 跨工作区验收与证据汇总

## 目标、前置与施工位置

本单元不新增业务能力；它只补齐缺失回归、运行完整矩阵并产出可复现证据。通过测试仅说明指定 commit
与本地环境的覆盖场景，不代表生产性能、模型质量或真实用户灰度结果。

前置：`01`--`08`、`09a-Web`、`09-Agent`、`09-Web`、`10-Web`、`11-Agent`、`11-Web` 与 `12a`
均已审查通过。后续：`13`。负责人：集成人。

这是唯一可按顺序使用两个工作区的单元：

```text
Web 测试工作区：D:\project\AI-QA-Assistant（web-dev）
Agent 测试工作区：D:\project\AI-QA-Assistant-agent-memory（agent-dev-infra）
```

允许修改仅限缺失测试和证据：

- `web/tests/utils/**`、`web/tests/routes/**`、`web/tests/integration/**`
- `agent/tests/unit/**`、`agent/tests/integration/**`
- `docs/memory-context-plan/evidence/12-acceptance-report.md`

禁止修改生产源码、schema/migration、环境秘密、部署脚本、公开 ChatResponse、Deep Research。若任一测试
暴露生产 bug，停止 12，回到对应原子单元修复并重新审查；不得在 12 顺手修业务代码。

## 必须覆盖的验收矩阵

| 层 | 必测不变量 |
| --- | --- |
| Web/数据库 | migration、chat ownership/匿名、sequence/幂等、SSE 失败不写助手、revision 失效、branch 隔离、删除级联、Fact proposal/confirm/revoke/过期/敏感/跨用户。 |
| Agent | Week-1 Runtime、Resolver 的 Snapshot/Tail/Fact/injection、Prompt 当前 query 一次、命中/空 Fact recall、候选命令、Planner 8/12/敏感/冲突、三 internal endpoint token/409/shared Agent。 |
| 开关 | persistent/fact/cache 三个默认关闭；cache 误开 fail closed；409 仅一次公开回退；Memory 故障不阻断回答且不泄露正文。 |
| 跨层 | 用户消息持久化 → trusted context → internal Agent response → assistant 成功持久化 → proposal/compaction plan → Web 事务写入；重启后 Snapshot+Tail 恢复；编辑/删除后旧 Memory 不可见。 |
| 隔离 | 浏览器无法提交权威 Memory；Fact 不产生 RAG citation；Chat/internal/compaction/reset 不导入、创建、读取或写入 Deep Research 状态。 |

跨层自动测试必须使用固定 mock Agent HTTP response 与 04 的 `memoryContract` schema，同时在 Agent
integration test 中验证同一 JSON fixture 被 private endpoint 接受。fixture 放在
`docs/memory-context-plan/evidence/fixtures/`，只含虚构 ID/文本，不能放真实用户数据或 token。若需要
真实本地服务才能验证某项，记录为“手工 smoke”，写明启动命令、端口、开关、清理步骤和结果；不因此宣称
端到端自动化通过。

## 固定执行顺序与命令

运行前后在两个工作区分别记录 `git show --no-patch --format=%H HEAD`；所有结果写入报告。

```powershell
Set-Location D:\project\AI-QA-Assistant\web
pnpm run db:generate
pnpm run db:migrate
pnpm exec vitest run
pnpm run typecheck
pnpm run lint
```

```powershell
Set-Location D:\project\AI-QA-Assistant-agent-memory
& .\.venv\Scripts\python.exe agent\scripts\run_week1_tests.py
& .\.venv\Scripts\python.exe -m pytest agent\tests
& .\.venv\Scripts\python.exe agent\scripts\check_contract.py
```

命令失败时保留原始失败输出、commit 和环境版本；不得用跳过、删测试或修改全局 timeout 伪造通过。Windows
临时 libSQL 目录若因句柄延迟无法删除，必须重跑验证退出码为 0 且记录该限制；不能只忽略非零退出。

## 证据报告、完成与停止条件

`12-acceptance-report.md` 必须含：Web/Agent commit、解释器与 pnpm 版本、每个命令、通过/失败数、
新增/未运行测试、手工 smoke 步骤和证据位置、已知限制、默认开关值、Chat/Deep Research 隔离结论。

完成条件：矩阵全部通过、所有公开兼容性和安全负向路径有证据、报告已审查。停止并回退到原单元：migration
阻断、任何跨用户/内部 token 泄露、Fact 进入错误 revision、Memory 失败阻断聊天、Deep Research 耦合、
或缺失人工验收证据。只有完成条件满足后才允许执行 13。
