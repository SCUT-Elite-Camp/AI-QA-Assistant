# CP2 Local Deep Research Week 1 成员 B 交付说明

## 交付范围

本周仅完成 W1-B1 和 W1-B2，不实现 Research Job API、Planner 或生产 Research Graph。

## 标准环境与命令

- Python：3.11.15
- 虚拟环境：`D:\miniconda3\envs\htc_qa`
- 关键依赖：`agent/requirements-week1.txt`

```powershell
D:\miniconda3\envs\htc_qa\python.exe -m pip install -r agent\requirements-week1.txt
D:\miniconda3\envs\htc_qa\python.exe agent\scripts\run_week1_tests.py
D:\miniconda3\envs\htc_qa\python.exe agent\scripts\run_week1_tests.py --collect-only
```

## W1-B1：生命周期和基线

- `ApplicationContainer` 在应用生命周期内复用 Agent、LLM、Tool Registry 和 SearchTool；
- `/api/chat` 的 `get_agent` 仍是 FastAPI Dependency，可以在测试中覆盖；
- FastAPI lifespan 只创建一套资源，预热使用相同 SearchTool；
- `/ready` 暴露初始化次数、初始化耗时和检索预热状态；
- SearchTool 的主题选项通过请求级 ContextVar 传递，不修改共享工具实例；
- 基线脚本使用确定性 Mock 记录 30 次请求的 P50/P95、LLM 调用数、Tool 调用数、初始化和阶段耗时。

```powershell
D:\miniconda3\envs\htc_qa\python.exe agent\scripts\run_chat_baseline.py `
  --iterations 30 `
  --output agent\docs\cp2\week1_chat_baseline_v1.json
```

该结果是无外部 LLM、Milvus和网络的可复现生命周期基线，不代表生产延迟，也不用于宣称未测量的优化百分比。

## W1-B2：LangGraph Spike

Spike 位于 `agent/deep_research/spikes/week1_langgraph.py`，只验证技术可行性。生产 Research Runtime 要在 Week 2 根据冻结 Contract 独立实现。选型结论见 `agent/docs/cp2/adr/0001-week1-langgraph-spike.md`。

## Gate G0 中成员 B 的结论

- 测试环境可复现；
- 应用资源可以跨连续请求复用；
- Chat 基线可以重复生成且包含环境信息；
- LangGraph/SQLite Checkpoint 在 Windows 环境通过 Spike；
- Week 2 可以基于可替换 Checkpointer 和 Mock 开发 Graph Skeleton。

Research Contract v1、Evidence v2 和共享错误码仍需成员 A+B 完成正式 Contract Review 后冻结。
