# Week 4 工作报告

## 完成时间

2026-07-03

## 本周目标

Week 4 目标是完成 Web 联调准备、全链路测试、异常场景测试、引用展示测试、Demo 问题集和 Agent 层技术收尾。

## 已完成内容

### 1. Web 联调接口稳定

- 保持 `POST /api/chat` 普通 JSON 响应不变。
- 响应字段稳定为 `trace_id`、`status`、`answer`、`message`、`citations`。
- 所有异常状态也保持同一响应结构。

### 2. CORS 支持

- FastAPI 已启用 CORS。
- 本地 Web 开发环境可直接访问 Agent 服务。

### 3. SSE 演示接口

新增：

```text
POST /api/chat/stream
```

该接口用于 Q1 Demo 的流式 UI 演示，事件包括：

- `token`
- `citations`
- `done`

普通 JSON 接口仍然是主交付接口。

### 4. 全链路测试

新增 Web 契约集成测试，覆盖：

- `/health`
- `/api/chat` success
- `/api/chat` invalid_query
- CORS preflight
- `/api/chat/stream` SSE 事件

### 5. Demo 问题集

新增：

```text
mock/demo_questions.json
```

用于 Web 联调和 Demo 验收。

### 6. 验收脚本

新增：

```text
scripts/run_week4_acceptance.py
```

用于快速验证健康检查、普通问答、异常响应和 SSE 事件。

### 7. 技术文档收尾

新增/更新：

- `docs/web_integration_guide.md`
- `docs/week4_report.md`
- `docs/final_handoff.md`
- `docs/integration_record.md`
- `docs/test_cases.md`
- `docs/four_week_plan.md`

## 验证结果

```text
python -m pytest
39 passed
```

```text
python scripts/check_contract.py
ChatRequest fields: filters, query, retrieval_mode, session_id, stream, top_k
ChatResponse fields: answer, citations, message, status, trace_id
```

```text
python scripts/run_week4_acceptance.py
week4_acceptance: passed
```

真实 Tool Layer 冒烟：

```text
USE_MOCK_RETRIEVAL=false python scripts/run_mock_demo.py
status: success
```

## 当前结论

Agent Layer Q1 已完成可演示版本：

- `/api/chat` 稳定
- Tool Layer 检索可接入
- Mock / Real 模式可切换
- 异常状态完整
- citations 可展示
- trace_id 可追踪
- SSE 演示接口可用于 Web 流式 UI

## 后续建议

- Web 层按 `docs/web_integration_guide.md` 完成最终联调。
- Demo 时优先使用普通 JSON 问答链路。
- SSE 仅作为 Q1 演示增强，不作为生产级流式能力。
- Q2 再替换真实 LLM、正式 Tool Layer 和权限过滤。
