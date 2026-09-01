# 06b Agent Memory 与冻结 Runtime 的迁移前核对（已完成）

## 目标

本单元是已完成的迁移前核对单，不是代码施工单。它只确认冻结 Runtime、旧实现来源、热点文件和后续单元的归属，防止一次“适配”吞掉 `04a`、`05`、`06`、`07`、`08`。执行 `06b` 时只能重新核对证据，不得修改任何 Agent/Web 源码、路由或测试。旧分支的测试结果不能替代后续功能单元的新版 Runtime 验收。

前置：`06a`。负责人：持有 Agent 热点写锁的集成人。为后续 `04`、`04a`、`05`、`06`、`07`、`08` 提供迁移矩阵；它本身不实施这些单元的代码。

施工位置：`D:\project\AI-QA-Assistant-agent-memory`（`agent-dev-infra`），仅只读检查。

## 输入、输出与非目标

输入：

- 冻结工作目录 `D:\project\AI-QA-Assistant-agent-memory` 的干净 `agent-dev-infra`：`5955cd0` 必须是 HEAD 的祖先，开始 Memory 代码迁移前其后的差异仅可为本目录的 docs-only 同步提交，或已独立验证、仅修改 `agent/requirements-week1.txt` 的可复现性修复；
- 旧实现参考 `web-dev@e303544`、`web-dev@8048e90`；
- 已锁定的内部 DTO/token 契约及 Web BFF `memory_context` 结构。

输出：冻结 Runtime 的接入证据、旧实现的参考范围和后续单元的唯一代码归属；不产出任何 Memory 功能代码。

非目标：不迁移任何代码、Web 文件、migration、Redis、USER Fact、自动确认、Fact lifecycle、UI；不采用 `feat/permission-hardening` 的 Bearer 鉴权；不接入 Deep Research。

## 已核对的基线证据

- 冻结代码祖先：`origin/agent-dev-infra@5955cd0`（`feat(agent): complete member B week 1 runtime work`）。
- 当前允许叠加经审查的 docs 同步提交；唯一非 docs 例外为 `b441acd`，仅修改
  `agent/requirements-week1.txt` 以补齐 Week-1 测试依赖，不改变 Runtime 或 Memory 行为。
- 最近记录的迁移前核对提交为 `e06acbe`；不得把旧 `web-dev@e303544` 或
  `web-dev@8048e90` 整体 cherry-pick/merge 到 Agent 开发线。
- 已验证命令：

```powershell
D:\project\AI-QA-Assistant-agent-memory\.venv\Scripts\python.exe agent\scripts\run_week1_tests.py
```

最近结果为 `214 passed, 1 warning`。它只证明冻结 Runtime 环境可回归，不证明任何 Persistent Memory 功能已实现。

## 后续代码归属矩阵（仅映射，不在本单元实现）

| 类别 | 文件/路径 | 后续唯一施工单 |
| --- | --- | --- |
| DTO/config | `schemas/chat.py`、`config/settings.py`、`.env.example`、API contract 与 DTO/config tests | `04` |
| 私有路由 | `api/internal_memory_routes.py`、`app.py` router 注册、`api/chat_routes.py` 的公开 reset 删除、端点/鉴权 tests | `04a` |
| Resolver | `memory/persistent_models.py`、`memory/context_resolver.py`、其配置和 unit tests | `05` |
| Prompt/Recall | `agent.py`、`orchestration/orchestrator.py`、`runtime/runner.py`、`memory_response_policy.py`，以及既有 internal handler 的 response 包装 | `06` |
| Compaction | `memory/compaction_planner.py`、敏感值过滤 helper、compaction handler/DTO 与 tests | `07` |
| History mutation | `04a` reset endpoint 完成后的 Agent 行为审查；Web 的 edit/delete 仍归 Web | `08`（默认审查） |
| 保持冻结 | `runtime/lifecycle.py`、`tools/executor.py`、`agent/deep_research/**`、所有 `web/**` | 任何单元均不得为 Memory 覆盖或迁移 |

## 重新核对步骤（只读）

1. 在 Agent worktree 运行 `git merge-base --is-ancestor 5955cd0 HEAD`、
   `git diff --name-only 5955cd0..HEAD` 和 `git status --short --branch`，确认本地基线和工作区。
2. 运行下列命令确认共享 Agent 和最终 Prompt 路径仍存在：

```powershell
rg -n "get_application_container|ApplicationContainer|def get_agent|def _build_messages|def run|llm\.chat" D:\project\AI-QA-Assistant-agent-memory\agent
```

3. 将任何新增候选文件映射到上表唯一的后续单元。跨越多个单元、需要改
   `runtime/lifecycle.py`/`tools/executor.py`、或无法确认最终模型调用点时，停止并报告。需要刷新
   remote 状态时单独征得允许后再 fetch，不能把 fetch 伪装成此只读施工单的一部分。

## 后续单元必须遵守的不变量

- 默认开关关闭时维持 `5955` 的 Chat 行为；
- 一个 HTTP 请求只从共享 `ApplicationContainer` 获得一个 Agent 实例，不新增全局实例；
- BFF 是 ChatMessage/Snapshot/Fact 的唯一数据库写入者；Agent 只消费可信 DTO、返回纯计划；
- 当前 query 在最终模型 messages 中出现一次；Fact 不是 citation；
- 内部 token 负向测试为 403，开关关闭为 409；
- Chat 和所有 Memory endpoint 不创建、读取或修改 Deep Research Job/状态。

## 建议命令与证据

```powershell
git -C D:\project\AI-QA-Assistant-agent-memory status --short --branch
git -C D:\project\AI-QA-Assistant-agent-memory show --no-patch --format=%H HEAD
rg -n "get_application_container|ApplicationContainer|def get_agent|def _build_messages|llm\.chat" D:\project\AI-QA-Assistant-agent-memory\agent
```

测试命令以冻结分支实际提供的 runner 为准；每个后续单元只运行其自身要求的 Memory 目标 pytest，跨层验证由 `12` 统一执行。命令、环境、通过/失败数必须进入交接；不可运行时明确写未运行和原因。

## 完成条件

本单元已完成的输出仅为上述基线证据和迁移矩阵。重新审查时必须确认：5955 仍为祖先、唯一依赖清单例外仍独立、共享 `get_agent()` 路径仍存在、没有未归属热点改动。任何失败都阻止后续 Agent 代码单元；任何要求在本单元写代码的请求都必须改由矩阵中的对应单元执行。
