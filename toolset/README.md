# 工具集层 CP2

本目录用于放置项目代码中的工具集层实现。CP2 在 CP1 统一接口基础上，补齐本地 vector 检索、BM25 检索和 hybrid RRF 融合逻辑。

## 开发规则

以下规则仅针对 Toolset 团队在 `toolset-dev` 分支上的工具集层开发工作：

代码注释、docstring、TODO、commit message 和 PR 标题统一使用英文。详细规则见：

```text
DEVELOPMENT_RULES.md
```

可选配置本地 commit 模板：

```powershell
git config commit.template .gitmessage.txt
```

## 调用方式

```python
from tool_layer import SearchTool

tool = SearchTool()
results = tool.search(
    query="项目 Q1 阶段需要完成哪些功能？",
    top_k=5,
    mode="hybrid",
    filters=None,
    min_score=0.0,
    trace_id="trace-xxxxxx-123456",
)
```

## 参数约定

| 参数 | 说明 |
| --- | --- |
| `query` | 用户问题，不能为空 |
| `top_k` | 默认 `5`，范围 `1-20` |
| `mode` | 默认 `hybrid`，可选 `vector`、`bm25`、`hybrid` |
| `filters` | CP1 可为空，预留 `doc_id`、`space`、`doc_type` |
| `min_score` | 默认 `0.0` |
| `trace_id` | Agent 层传入，工具集层记录日志 |

## 返回结果

```json
{
  "doc_id": "doc_001",
  "chunk_id": "doc_001::chunk_0",
  "chunk_index": 0,
  "chunk_text": "...",
  "title": "document title",
  "score": 0.85,
  "vector_score": 0.82,
  "bm25_score": 0.66,
  "source_url": ""
}
```

## CP2 说明

- 当前默认 backend 是本地 JSONL 检索，用于接口联调和算法逻辑验证。
- `vector` 模式使用 TF-IDF cosine similarity 作为本地向量检索入口。
- `bm25` 模式使用标准 BM25 公式。
- `hybrid` 模式使用 RRF 融合 vector 和 BM25 排名。
- hybrid 结果按 `(doc_id, chunk_index)` 去重。
- 返回结果保留 `vector_score` 和 `bm25_score`。
- 后续可将 vector 后端替换为 Milvus，不改变 Agent 调用接口。
- 检索成功但无结果时返回 `[]`。
- 检索服务异常时抛出 `RetrievalError`。
- 如果底层没有 `chunk_id`，工具集层按 `{doc_id}::chunk_{chunk_index}` 自动生成。
- 如果底层没有 `title`，工具集层优先根据 `doc_id` 查询 `data/documents/{doc_id}.json`，查不到则用 `doc_id` 兜底。

## 验证

在 `toolset` 目录下运行：

```powershell
python -m unittest discover -s tests
```
