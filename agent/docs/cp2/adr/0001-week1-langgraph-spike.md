# ADR-0001：CP2 Local Research 使用 LangGraph 状态图

- 状态：Accepted for CP2 implementation
- 日期：2026-08-22
- 决策人：成员 B；共享 Contract 仍需 A+B Review

## 背景

CP2 Local Deep Research 需要三个确定性节点、计划审批中断、SQLite Checkpoint、进程重启恢复、错误停留在安全状态，以及按 `research_id/thread_id` 查询当前状态。业务契约不能继承框架类型，测试还必须能替换 Checkpointer。

## Spike 环境

- Windows
- Python 3.11.15
- `langgraph==1.2.11`
- `langgraph-checkpoint==4.2.0`
- `langgraph-checkpoint-sqlite==3.1.1`

## 验证结果

Spike 使用 `prepare → approval → finalize` 三个确定性节点，验证了审批 Interrupt、批准后继续、SQLite 重启恢复、异常安全状态、Checkpointer 替换、普通 TypedDict 业务状态和 JSON 序列化。

## 决策

CP2 采用 LangGraph 作为固定 Research Graph 的执行框架，SQLite Checkpointer 用于 Local MVP。业务 Contract、Repository 和 API 保持框架无关，通过 Adapter 隔离 Checkpointer。

本决策不授权开发通用图平台，也不允许模型动态添加无限节点、跳转或预算。生产代码只能实现计划中冻结的固定主干和受限条件边。

## 后果和约束

- Week 2 基于 Spike 建立独立 `deep_research` Graph Skeleton；
- Spike 代码不作为生产 Job Runtime 直接复用；
- SQLite 连接生命周期必须由 Runtime/Repository 显式持有；
- 破坏性升级 LangGraph 版本前必须重跑中断、恢复和失败 Checkpoint 测试；
- 若后续出现 Windows、序列化或恢复阻塞，可保留业务 Contract 并替换为最小状态机。

