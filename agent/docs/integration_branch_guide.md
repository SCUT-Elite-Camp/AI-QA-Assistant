# Agent 层集成分支说明

常规 Agent 团队集成分支为 `agent-dev`。2026-10-09 全系统整合使用 `integration/agent-demo-access-evidence`，以 #63 `cdbe02b` 为共同基线，保留 partner 的质量/UI 修复，再提出到 `dev` 的 PR。验收缺口和历史归属见[交接报告](../../docs/pr63-integration-acceptance.md)。

## 分支职责

- `feature/agent-core`：Agent 业务主流程分支，负责 `api`、`service`、`prompt`、`llm`、`formatter`。
- `feature/agent-infra`：Agent 基础设施分支，负责 `retrieval`、`logger`、`trace`、`schemas`、`config`、`tests`。
- `agent-dev`：Agent 层集成分支，第二周末以后用于合并 Core 和 Infra 的可运行版本。
- `main`：稳定分支，不直接开发。

## 第三周协作流程

1. 每个人开发前先从 `agent-dev` 更新本地基线。
2. Core 和 Infra 的改动先在各自 feature 分支完成。
3. 合并前必须本地通过 `python -m pytest`。
4. 合并到 `agent-dev` 后再跑一次 `python -m pytest` 和 `python scripts/run_mock_demo.py`。
5. 涉及 `/api/chat`、检索字段、状态码、citations 的改动，必须同步更新 `docs/API_CONTRACT.md` 和 `docs/interface_contract.md`。

## 冲突处理原则

- `/api/chat` 请求和响应格式以 `docs/API_CONTRACT.md` 为准。
- Tool Layer 检索接口以 `docs/cp1/tool_layer_interface.md` 为准。
- `ChatRequest`、`ChatResponse`、`RetrievalResult` 字段不能在未同步文档和测试的情况下改名或删除。
- 隔离测试可用 Mock；真实验收须显式配置实际服务，不得静默退回 Mock。本次跨层协议以根接入文档为准。

## 真实 Tool Layer 冒烟测试

当 `tool_layer.SearchTool` 在当前 Python 环境中可导入后，执行：

```powershell
$env:USE_MOCK_RETRIEVAL = "false"
$env:TOOL_LAYER_IMPORT = "tool_layer"
$env:TOOL_LAYER_CLASS = "SearchTool"
python scripts/run_mock_demo.py
```

验收标准：

- 请求能够走到 `SearchTool.search()`。
- Agent 传入同一个 `trace_id`。
- 有结果时返回 `status=success` 且包含 citations。
- 无结果时返回 `status=no_relevant_context`。
- 检索异常时返回 `status=retrieval_error`，服务不崩溃。
