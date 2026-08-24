# Unit 12 跨工作区验收报告

> 日期：2026-08-24。此报告只描述下列本地工作区、当前未提交改动和本地测试环境；它不代表生产性能、模型质量、部署或灰度结果。

## 1. 基线与环境

| 项目 | 值 |
| --- | --- |
| Web 工作区 / 分支 / HEAD | `D:\project\AI-QA-Assistant` / `web-dev` / `49efbfacd10afb5aea0e5988de2d01bdbcee5f55` |
| Agent 工作区 / 分支 / HEAD | `D:\project\AI-QA-Assistant-agent-memory` / `agent-dev-infra` / `d381d9e8515ade1fbe7c0c60220e2540901fff45` |
| Node package manager | pnpm `11.19.0` |
| Agent interpreter | Python `3.11.9` (`.venv`) |

两个工作区在验收时都包含尚未提交的已审查 Memory 实现与本单元的测试/fixture 变更。因此上述 HEAD 只能标识共同父基线，复现本报告必须同时使用对应工作区的未提交 diff；不得将它误写为仅凭 commit 可复现的发布证据。

## 2. 共享跨层 Fixture

新增的 fixture 只使用虚构 ID、虚构文本且不含 token、真实用户数据或部署配置：

- `fixtures/internal-chat-request.json`：Web `internalChatRequestSchema` 校验并由 Agent private `/api/internal/chat` 接受。
- `fixtures/internal-chat-response.json`：Web `internalChatResponseSchema` 校验并作为 BFF internal-client 的固定 mock HTTP response。

两个工作区的同名文件通过 SHA-256 校验字节一致：

| 文件 | SHA-256 |
| --- | --- |
| `internal-chat-request.json` | `7D23B5F6D6EC375611D5635784BB3C7C334C7FE945DB4F28E7CE395DC6AAB869` |
| `internal-chat-response.json` | `00AA60A890851155250A80F91CEDD606F89108F025DF82444F78F8557C1C374F` |

新增/补齐的回归：

- Web `tests/utils/memoryContract.test.ts` 与 `tests/utils/agentInternalClient.test.ts` 共同消费 fixture 并使用 04 的 schema。
- Agent `tests/integration/test_internal_memory_routes.py::test_internal_chat_accepts_the_shared_web_contract_fixture` 将同一 request fixture 提交到 private endpoint。
- Web `tests/integration/chat-memory-flow.test.ts` 的测试 mock 同步 11-Web 新增的无正文 metrics/logger API；这是测试隔离修复，不改变生产行为。

## 3. 自动化命令与结果

### Web

| 命令 | 结果 |
| --- | --- |
| `pnpm run db:generate` | 通过；9 tables；无 schema change、无新 migration。 |
| `pnpm run db:migrate` | 通过；本地 migration 成功应用。 |
| `pnpm exec vitest run` | 通过；17 files、105 tests。 |
| `pnpm run typecheck` | 已执行，退出 `2`；仅复现既有 Vue UI 类型错误（`src/components/chat/**`、`src/components/ModalSelectTopic.vue`、`src/pages/topics/index.vue`），依据已授权基线豁免记录为非本单元 Memory 回归。 |
| `pnpm run lint` | 通过；0 errors、219 existing warnings。 |

### Agent

| 命令 | 结果 |
| --- | --- |
| `& .\.venv\Scripts\python.exe agent\scripts\run_week1_tests.py` | 通过；308 passed、3 warnings。 |
| `& .\.venv\Scripts\python.exe -m pytest agent\tests` | 通过；308 passed、3 warnings。 |
| `& .\.venv\Scripts\python.exe agent\scripts\check_contract.py` | 通过；公开 `ChatRequest`/`ChatResponse` 字段清单未含 Memory 字段。 |

运行中发现本地 `.venv` 的 `ormsgpack` 和 `orjson` 原生 wheel 损坏，导致首次收集失败。已仅在本地虚拟环境以 `pip install --force-reinstall --no-cache-dir` 重装 `ormsgpack==1.12.2` 与 `orjson==3.12.0`；未修改仓库依赖清单或生产源码，随后两次 Agent 全量回归均通过。

## 4. 验收矩阵结论

| 维度 | 本地证据与结论 |
| --- | --- |
| Web/数据库 | 全量 Vitest 通过；migration 生成无差异、迁移成功；覆盖 ownership、sequence/幂等、SSE、revision、branch、删除与 Fact 生命周期回归。 |
| Agent | 两次 308-case 全量回归通过；覆盖 Runtime、Resolver Snapshot/Tail/Fact/injection、prompt 单次 query、recall、proposal、planner、private endpoints 与 shared Agent。 |
| 开关与安全降级 | Web/Agent tests 覆盖 persistent/fact 默认关闭、cache fail-closed、409 一次公开回退、无正文观测和失败非阻断。 |
| 跨层合同 | 共享 request/response fixture 在 Web schema/BFF client 与 Agent private endpoint 三处验证；实际数据库到真实 HTTP 服务的端到端进程编排尚未执行。 |
| 隔离 | Web public schema 与 Agent endpoint tests 证明 browser/public request 不接收 trusted Memory；Agent production-lifespan test 覆盖 Chat/Memory 不加载 Deep Research。 |

## 5. 手工 Smoke 与已知限制

### 已完成的匿名入口检查（部分证据）

- 时间：2026-08-24；地址：`http://127.0.0.1:3000/`。
- 使用当前 Codex in-app browser 的真实 DOM 与页面截图检查：页面显示“Sign in with GitHub”，未显示 SESSION Fact 面板或“保存为记忆”入口。
- 此结果只证明当前未登录首页不会暴露 Fact UI；它不覆盖匿名访问 private/public chat URL、Fact API 的 HTTP 响应或任何已认证行为。截图仅作为本次受控 Codex 任务的内联证据，尚无可归档的本地录屏/截图文件。

`web/tests/manual/10-fact-web-experience.md` 的真实浏览器/OAuth 手工 smoke **未完成**：2026-08-24 已按用户授权点击本地页面的 GitHub 登录入口，但该入口被桌面浏览器打开为 `http://localhost:3000/auth/github`，in-app browser 的 URL 安全策略拒绝接管该回调页；未进入 GitHub、未输入或传输凭据。独立本地 HTTP 检查确认 `http://127.0.0.1:3000/` 与 `http://localhost:3000/` 均返回 `200`，因此此记录不把问题归因为服务未启动。仍缺少已认证 Web + Agent 环境、单账号私有 chat、匿名窗口和可归档截图/录屏位置。不得将自动化 mock 结果描述为 OAuth、SSE UI 或真实本地模型端到端通过。

建议在受控本地环境补齐：使用 `PERSISTENT_MEMORY_ENABLED=true`、`SESSION_FACT_ENABLED=true`，以一个已授权 GitHub 账号和匿名窗口完成私有会话、跨 chat 与匿名隔离的真实浏览器检查。不同已认证用户之间的隔离不要求为本次手工 smoke 新增第二个 GitHub 账号，继续由已通过的仓储/API 自动化回归覆盖。严格执行该手工脚本的 proposal、confirm、revoke、敏感拒绝、取消 SSE、跨 chat/匿名隔离与 exact-recall 标签步骤；截图/录屏只存放在受控位置，不记录 token 或真实用户数据。

当前 `pnpm run typecheck` 的 UI 基线错误也仍需由 UI owner 单独修复或再次明确豁免；本单元没有修改这些文件。

## 6. 进入 Unit 13 的判定

自动化 Memory 矩阵已通过（Web typecheck 已按既有豁免记录），但缺少施工单要求的真实浏览器/OAuth 手工 smoke 证据。因此 **暂不允许执行 Unit 13**。完成并保存手工 smoke 证据后，再审查 Unit 12；两个工作区的当前未提交改动也应按工作区拆分提交，以使该证据能够由确定的 commit 复现。
