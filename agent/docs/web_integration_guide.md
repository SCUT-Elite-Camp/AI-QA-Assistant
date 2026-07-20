# Web 联调指南

## 服务启动

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
```

期望：

```json
{"status":"ok"}
```

## 普通 JSON 问答

接口：

```text
POST /api/chat
```

请求示例：

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "web-session-001",
  "top_k": 5,
  "retrieval_mode": "hybrid",
  "filters": null,
  "stream": false
}
```

Web 必须按以下字段解析响应：

- `trace_id`
- `status`
- `answer`
- `message`
- `citations`

展示建议：

- `status == "success"`：展示 `answer` 和 `citations`。
- `status != "success"`：展示 `message`，不要展示空 `answer`。
- 所有状态都保留或展示 `trace_id`，方便联调排查。
- `citations` 按 `citation_id` 与答案中的 `[1]`、`[2]` 对应展示。

## 状态码

| status | Web 行为 |
| --- | --- |
| `success` | 展示答案和引用。 |
| `invalid_query` | 展示参数错误提示。 |
| `no_relevant_context` | 展示资料不足提示。 |
| `retrieval_error` | 展示检索服务异常提示。 |
| `llm_error` | 展示模型服务异常提示。 |

## SSE 演示接口

接口：

```text
POST /api/chat/stream
```

当前 Q1 使用已生成的普通答案模拟 SSE 事件，便于 Web 演示流式 UI。

事件格式：

```text
event: token
data: {"content":"..."}

event: citations
data: [...]

event: done
data: {"trace_id":"trace-xxx","status":"success","message":"","citations_count":3}
```

## CORS

Q1 Agent 服务已开启 CORS，允许本地 Web 开发环境直接访问。

## 验收命令

```bash
python -m pytest
python scripts/check_contract.py
python scripts/run_week4_acceptance.py
```

真实 Tool Layer 冒烟：

```powershell
$env:USE_MOCK_RETRIEVAL="false"
python scripts/run_mock_demo.py
```
