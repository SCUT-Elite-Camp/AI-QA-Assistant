# 06a Agent 集成基线锁定

## 目标

消除 Agent 编排热点并行修改造成的“施工单执行到一半无法确定最终 Prompt 路径”的风险。所有 Agent Memory 集成代码均固定在已验证的 `origin/agent-dev-infra` 基线之上。

## 已锁定基线

```text
remote branch: origin/agent-dev-infra
commit: f7866f4
subject: feat(agent): add complexity gating and subquery routing
base dev commit: 6e4ee17d9eb53c318fe22aa4cadafb6f294370e3
```

执行 Agent 必须在开始 `06` 前运行：

```powershell
git -C D:\project\AI-QA-Assistant fetch origin
git -C D:\project\AI-QA-Assistant show --no-patch --format=%H origin/agent-dev-infra
```

输出必须仍为 `f7866f4`。如远程已变化，停止并由 Agent owner 更新本施工单、重新审查实际调用路径；不得默默跟随最新 remote。随后从该 commit 创建/使用 Agent 团队分支，不能在当前 `dev` 直接改热点文件。

## 合入规则

若 `agent-dev-infra` 已合入 `dev`，集成人先取得合入 commit，并验证 `f7866f4` 是其祖先：

```powershell
git -C D:\project\AI-QA-Assistant merge-base --is-ancestor f7866f4 <merged-commit>
```

成功后可把 `<merged-commit>` 替换为本文件的新基线，并在交接记录原 hash、更新日期和冲突处理结果。若失败，不实施 `06`。

## 最终模型调用点检查

在锁定基线上，执行 Agent 必须用 `rg` 确认：

```powershell
rg -n "_build_messages|messages=self\._build_messages|llm\.chat|chat\(" D:\project\AI-QA-Assistant\agent\agent
```

将“最终实际调用模型的函数路径”和“ContextArtifact 注入点”记录在 `06` 的交接中。若新 complexity/subquery 分支绕过现有 `AgentRunner._build_messages()`，以最终模型调用点为准，但仍必须满足 query 只追加一次、RAG system rules 在前、Fact 不变成 citation 的不变量。

## 完成标准

`06` 的 PR 描述包含基线 commit、冲突文件、最终调用点、完整 pytest 结果。没有这些信息，不得声称已集成持久 Memory。
