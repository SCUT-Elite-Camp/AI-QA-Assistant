# 06a Agent 集成基线锁定（5955）

## 目标

把尚未迁移的 Agent Memory 实现对齐到已冻结的 Agent Runtime，避免把旧 Runtime 的调用假设带入新代码。本单元是 `06` 的强制前置，只定义基线、热点所有权和接入证据；不迁移业务代码。

## 当前冻结代码基线

```text
remote branch: origin/agent-dev-infra
commit: 5955cd0
subject: feat(agent): complete member B week 1 runtime work
base dev commit: 6e4ee17d9eb53c318fe22aa4cadafb6f294370e3
```

Memory 的 Agent 实现必须在下列独立工作目录进行人工迁移，而不是从旧 `web-dev` 分支整体 cherry-pick。该分支可先包含经审查的 docs-only 同步提交，但在开始第一笔 Memory 代码前仍必须保留 `5955cd0` 的全部代码：

```text
D:\project\AI-QA-Assistant-agent-memory
local branch: agent-dev-infra
upstream: origin/agent-dev-infra
```

开工前必须运行：

```powershell
git -C D:\project\AI-QA-Assistant-agent-memory fetch origin
git -C D:\project\AI-QA-Assistant-agent-memory merge-base --is-ancestor 5955cd0 HEAD
git -C D:\project\AI-QA-Assistant-agent-memory diff --name-only 5955cd0..HEAD
git -C D:\project\AI-QA-Assistant-agent-memory status --short --branch
```

输出必须证明 `5955cd0` 仍是 HEAD 的祖先，且在第一笔代码提交前差异仅限
`docs/memory-context-plan/**`，工作区也必须干净。若远程或 owner 宣布的冻结代码基线发生变化，立即停止，由 Agent owner 更新本文件、`06b` 和所有引用该基线的测试证据；不得静默跟随 remote。

## 必须保留的新版 Runtime 事实

1. `agent/app.py` 的 lifespan 负责创建、启动并保存 `ApplicationContainer`，同时保留 warm-up 和 `/ready` 语义。
2. `agent/agent/api/chat_routes.py` 的 `get_agent()` 从共享 `ApplicationContainer` 取得 Agent 实例。内部 Memory 路由必须复用该依赖，不得自行构造 `Agent`、`AgentRunner` 或长生命周期客户端。
3. `agent/agent/runtime/runner.py` 的 `AgentRunner._build_messages()` 是当前最终 Prompt 组装点：基础 system prompt 在前，history 随后，当前 `query_plan.original_query` 最后且只能追加一次。
4. `agent/agent/runtime/lifecycle.py` 的容器生命周期和 `agent/agent/tools/executor.py` 的请求上下文/执行器能力属于他人已冻结交付，Memory 不得覆盖、回退或重写它们。

上述路径是当前证据，不等同于永恒接口。每次实际迁移前均应再次阅读相关源码并记录实际行号。

## 单线写锁与职责边界

- `origin/agent-dev-infra` 是当前唯一 Agent 集成线；Memory 集成人取得该线的写锁后，才可修改 `agent.py`、`orchestrator.py`、`runner.py`、`app.py`、`chat_routes.py`、schemas/config 和内部路由。
- 未持锁同学只可提交独立新文件、测试建议或文档；如必须触碰热点文件，先把变更交给当前持锁人串行合入。
- `web-dev` 保留 Web/BFF、数据库和 UI 工作；不得把 Web 的数据库 Repository、migration 或 route 直接迁入 Agent 工作目录。
- 本 Memory 方案只服务 Chat。不得导入/调用 `agent/deep_research/**`，不得从 Chat 或内部 Memory API 创建 Research Job，也不得把 Chat 的 Snapshot、Fact、Tail 作为 Deep Research 的状态。

## 最终调用链检查

执行 Agent 必须在开始 `06` 前确认当前链路：

```powershell
rg -n "get_application_container|ApplicationContainer|def get_agent|def _build_messages|def run|llm\.chat" D:\project\AI-QA-Assistant-agent-memory\agent
```

交接中必须写明实际调用链：

```text
HTTP Chat/internal route -> shared get_agent -> Agent -> Orchestrator
-> AgentRunner._build_messages -> llm.chat
```

若实际最终模型调用点已不再经过 `_build_messages()`，停止 `06`，先更新本文件和 `06`；随后在新的最终调用点保持同样不变量：基础/RAG system rules 在前、Memory 作为受隔离的 system context、当前 query 只出现一次、Fact 不会伪装成 citation。

## 迁移来源与方式

旧实现可作为行为参考，来源为 `web-dev` 的 `e303544` 和 `8048e90`。只允许按文件和职责人工移植，绝不整体合并旧提交：

- 可直接新增后再审查：`agent/agent/memory/**`、`agent/agent/api/internal_memory_routes.py`、对应新测试；
- 必须三方人工合并：`agent.py`、`api/chat_routes.py`、`config/settings.py`、`orchestration/orchestrator.py`、`runtime/runner.py`、`schemas/chat.py`、`app.py`、`.env.example`、API contract 与既有测试；
- 必须保留冻结版本：`runtime/lifecycle.py`、`tools/executor.py`、`deep_research/**` 及所有 Web 文件。

详细迁移施工见 `06b-agent-infra-5955-reconciliation.md`。

## 停止条件

- `origin/agent-dev-infra` 不再是 `5955cd0`，或工作区存在未归属的热点改动；
- `get_agent()` 不再从共享容器获得实例，或最终模型调用链无法确认；
- 迁移要求修改 `runtime/lifecycle.py`、`tools/executor.py`、Deep Research 或公开浏览器 Chat 契约；
- 任一基线测试、Prompt 单次 query 不变量或 Chat/Research 隔离测试失败。

## 完成标准

`06`/`06b` 的交接必须包含：基线 hash、迁移文件矩阵、冲突处理说明、最终调用路径、完整测试命令及结果。缺少任一项，不得声称持久 Memory 已适配新版 Runtime。
