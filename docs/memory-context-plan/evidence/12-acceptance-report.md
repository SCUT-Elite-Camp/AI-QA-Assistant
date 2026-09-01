# Unit 12 跨工作区验收报告

> 日期：2026-08-24。此报告只描述下列本地工作区、当前未提交改动和本地测试环境；它不代表生产性能、模型质量、部署或灰度结果。

## 1. 基线与环境

| 项目 | 值 |
| --- | --- |
| Web 工作区 / 分支 / HEAD | `D:\project\AI-QA-Assistant` / `web-dev` / `eef49621c064362cd318aef2deaa00b60c1d9462` |
| Agent 工作区 / 分支 / HEAD | `D:\project\AI-QA-Assistant-agent-memory` / `agent-dev-infra` / `4b3f333e213d0a60a78b32ba0a3781bb0aab3343` |
| Node package manager | pnpm `11.19.0` |
| Agent interpreter | Python `3.11.9` (`.venv`) |

Web 的可信 recall 标签和 SSE 取消修复已在 `eef4962` 独立提交；本报告随后以独立证据提交保存。Agent 未为本次手工 smoke 修改源码；其本地 `data-persistence/data/chat_history.db` 是服务运行产生的数据变化，不属于代码或证据提交。复现本报告应使用这两个确定的提交及下述本地开关，而不得将结果表述为生产发布证据。

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
| `pnpm exec vitest run` | 通过；17 files、108 tests。 |
| `pnpm run typecheck` | 已执行，退出 `2`；仅复现既有 Vue UI 类型错误（`src/components/chat/**`、`src/components/ModalSelectTopic.vue`、`src/pages/topics/index.vue`），依据已授权基线豁免记录为非本单元 Memory 回归。 |
| `pnpm run lint` | 通过；0 errors、219 existing warnings。 |

受控执行环境中首次直接调用 `pnpm exec vitest run` 未将本地 `.bin` 加入 `PATH`，且 Vite 需要写入临时配置缓存；确认本地 `vitest` 二进制及依赖完整后，显式加入 `web/node_modules/.bin` 并允许该临时缓存写入，使用同一命令重跑并得到上述 108 项通过结果。未重装、升级或修改任何依赖。

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

## 5. 真实本地 Smoke 与已知限制

所有步骤于 2026-08-24 在受控本地环境完成：`PERSISTENT_MEMORY_ENABLED=true`、`SESSION_FACT_ENABLED=true`，Web 为 `localhost:3000`，Agent private service 为 `localhost:8000`。GitHub OAuth 已由用户在本机浏览器完成；验收自动化未读取、导出或记录密码、Cookie、token 或真实 Fact 值。DOM 断言和无凭据 HTTP 命令的原始结果均在本次 Codex 运行输出中，以下仅保留脱敏的可复现结论。

| 场景 | 自动化步骤与结果 |
| --- | --- |
| proposal / confirm / revoke | 已认证私有 chat 中，以受控非敏感文本创建 proposal、确认 SESSION Fact、撤销并刷新；卡片、到期日与撤销后的不可见性均符合预期。 |
| 敏感拒绝 | 对受控敏感模式文本执行“保存为记忆”，页面显示“该内容不能保存为记忆”；未创建 Fact。 |
| exact recall 标签 | 已确认的 SESSION Fact 后发送明确回忆请求。private `/api/internal/chat` 返回 `recall.handled=true`，页面显示正确的确定性回忆文本及“来自已确认会话记忆”标签。`chat-memory-flow.test.ts` 同时验证 public fallback 即使伪造同形字段也不能发出该标签。 |
| SSE 取消 | 发送受控请求后，按钮在 `submitted` 状态为 `type=button`（stop），自动点击后恢复为 `type=submit`（send）；页面最后仅有该用户消息、无对应 assistant 消息且无错误提示。修复前页面错误地将 `submitted` 映射为 `ready`，导致无法取消；修复已在 `eef4962`。 |
| 跨 chat 隔离 | 在含已确认 SESSION Fact 的旧私有 chat 后，新建第二个私有 chat 并请求回忆。新 chat 的 DOM 不含旧 Fact 文本、不含“本会话记忆”面板，也不含“来自已确认会话记忆”标签。 |
| 匿名隔离 | 不携带任何凭据，对旧 chat、新 chat 的 `GET /api/chats/:id/memory/facts` 及对旧 chat 的 proposal `POST` 均返回 `404`；匿名调用既不能读取也不能创建 Fact。 |

局限：这是一个真实本地、单账号、受控数据的验收，不覆盖第二个已认证账号的浏览器会话；该隔离维度仍由 ownership/跨用户仓储与 API 自动化回归覆盖。Agent 本地日志中检索模型依赖的 warm-up 失败不影响本次确定性 Fact recall，但不能据此宣称 RAG 检索质量已验收。`pnpm run typecheck` 的既有 UI 错误仍按授权基线豁免，须由 UI owner 独立处理。

## 6. 进入 Unit 13 的判定

自动化 Memory 矩阵已通过（Web typecheck 按既有豁免记录），且真实本地 smoke 已覆盖 proposal、confirm、revoke、敏感拒绝、SSE 取消、跨 chat/匿名隔离与 exact-recall 标签。因此 **允许开始 Unit 13 发布就绪审查**；灰度或生产发布仍需 Unit 13 所列人工授权。
