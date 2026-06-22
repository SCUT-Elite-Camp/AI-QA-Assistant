# Tool Layer 检索接口契约

本文档记录 Agent 层接入 Tool Layer 的 CP1 检索接口。Agent 层通过 `RetrievalAdapter` 调用 `SearchTool.search()`，并统一转换为 `RetrievalResult`。

## 调用方式

```python
from tool_layer import SearchTool

tool = SearchTool()

results = tool.search(
    query="user question",
    top_k=5,
    mode="hybrid",
    filters=None,
    min_score=0.0,
    trace_id="trace-xxxxxx-123456",
)
```

## search 参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `query` | `str` | 无 | 用户问题，不能为空。 |
| `top_k` | `int` | `5` | 返回结果数量，有效范围为 `1-20`。 |
| `mode` | `str` | `hybrid` | 检索模式，支持 `vector`、`bm25`、`hybrid`。 |
| `filters` | `dict \| None` | `None` | 预留过滤条件，可用于 `doc_id`、`space`、`doc_type`。 |
| `min_score` | `float` | `0.0` | 最低相关度阈值。 |
| `trace_id` | `str \| None` | `None` | Agent 层传入，用于日志和链路追踪。 |

## 返回格式

Tool Layer 返回 `list[dict]`，每个结果包含：

```json
{
  "doc_id": "doc_001",
  "chunk_id": "doc_001::chunk_0",
  "chunk_index": 0,
  "chunk_text": "retrieved chunk text",
  "title": "document title",
  "score": 0.85,
  "source_url": ""
}
```

Agent 层依赖字段：

- `chunk_text`：用于组装 Prompt。
- `doc_id`、`chunk_id`、`chunk_index`、`title`、`score`、`source_url`：用于生成 citations。
- 如果 `chunk_id` 缺失，Agent 层按 `{doc_id}::chunk_{chunk_index}` 补齐。
- 如果 `title` 缺失，Agent 层回退到 `doc_id`。

## 异常处理

| 场景 | Tool Layer 行为 | Agent 层处理 |
| --- | --- | --- |
| 检索成功且有结果 | 返回结果列表 | 继续组装 Prompt 并调用 LLM。 |
| 检索成功但无结果 | 返回 `[]` | 返回 `no_relevant_context`。 |
| 空问题、非法 `top_k` 或非法 `mode` | 抛出参数异常 | 返回 `retrieval_error` 或由请求校验拦截。 |
| 检索后端异常 | 抛出检索异常 | 返回 `retrieval_error`。 |

## Agent 层集成要求

- 默认 `top_k=5`。
- 默认 `mode="hybrid"`。
- Agent 层生成并传递 `trace_id`。
- Mock 模式和真实 Tool Layer 模式通过 `USE_MOCK_RETRIEVAL` 切换。
- 真实模式使用 `TOOL_LAYER_IMPORT` 和 `TOOL_LAYER_CLASS` 动态加载 Tool Layer。
