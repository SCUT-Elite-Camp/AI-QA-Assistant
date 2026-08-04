# Agent Layer Q1 交接说明

## 当前可运行能力

- `GET /health`
- `POST /api/chat`
- `POST /api/chat/stream`
- Mock Retrieval
- Tool Layer `SearchTool.search()` 真实模式冒烟
- Mock LLM
- OpenAI-compatible LLM Client 预留
- 统一响应结构
- citations 生成和引用一致性修正
- `invalid_query`
- `no_relevant_context`
- `retrieval_error`
- `llm_error`
- trace_id 日志链路
- Web CORS

## 推荐启动方式

```bash
cd agent-layer
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## 推荐验收命令

```bash
python -m pytest
python scripts/check_contract.py
python scripts/run_week4_acceptance.py
```

## 真实检索模式

```powershell
$env:USE_MOCK_RETRIEVAL="false"
$env:TOOL_LAYER_IMPORT="tool_layer"
$env:TOOL_LAYER_CLASS="SearchTool"
python scripts/run_mock_demo.py
```

## Web 对接重点

- 普通问答使用 `/api/chat`。
- 流式演示使用 `/api/chat/stream`。
- `status == success` 展示 `answer` 和 `citations`。
- `status != success` 展示 `message`。
- 保留 `trace_id` 用于排查。

## 已知边界

- Q1 不做真实权限系统。
- Q1 不连接真实 HSBC 系统或真实敏感数据。
- Q1 默认使用 Mock LLM。
- SSE 是演示级流式事件，不是生产级真实 LLM streaming。
- Tool Layer 当前为 CP1 smoke stub，Q2 可替换正式检索实现。

## Week 4 后建议

- 与 Web 层完成最终 Demo 页面联调。
- 将 Demo 问题集跑一遍并记录 trace_id。
- Q2 再推进真实 LLM、正式检索质量、权限过滤和生产部署。
