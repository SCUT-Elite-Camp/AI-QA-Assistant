# Toolset 工具层

`toolset` 保存 Agent 可调用的工具，以及应用和数据导入流程使用的检索基础模块。

## 开发规则

本目录规则适用于 `toolset-dev` 分支上的 Toolset 工作。代码注释、docstring、TODO、
commit message 和 PR 标题统一使用英文。完整流程见
[DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md)。

## 当前检索调用链

```text
AgentRunner -> ToolExecutor -> ToolRegistry -> SearchTool
            -> 向量检索（Embedding + Milvus）和/或 BM25
            -> 规范化证据 -> Agent 答案格式化
```

Registry 直接构造 `SearchTool`。Hybrid 模式在 `SearchTool` 内融合向量和 BM25 结果。

2026-10-09 整合中 Chat 与 Research 共用企业搜索/原文读取。工具保留 `source_version`、正文 `content_hash`、locator 和 `evidence_ref`，Agent 核对文本属于同一权威原文，不能将旧索引片段绑定新版本。private 工具 HMAC/owner/KB/作用域约束见[跨层契约](../docs/access-evidence-integration.md)，携内部凭据的 HTTP 请求拒绝重定向。Wiki 导航元数据因自身访问证明不足暂被隔离。

## SearchTool 接口

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

| 参数 | 说明 |
| --- | --- |
| `query` | 必填查询文本 |
| `top_k` | 结果数量，范围 1–20，默认 5 |
| `mode` | `vector`、`bm25` 或 `hybrid`，默认 `hybrid` |
| `filters` | 可选文档、空间或文档类型限制 |
| `min_score` | 最低归一化分数，默认 0 |
| `trace_id` | 可选请求标识，会写入检索日志 |

返回结果包含文档和分块标识、标题、内容、来源 URL 和分数。检索成功但没有命中时
返回空列表；参数错误抛出 `RetrievalParameterError`，后端故障抛出 `RetrievalError`。

## 索引与存储

`BM25Index` 是当前用于证据检索的词法索引，由数据处理 Pipeline 根据处理后的文档构建并持久化。
大纲导航则从活动文档记录中读取 Section 元数据。向量检索使用配置的 Embedding 提供方和 Milvus。
相关实现位于 `retrieval/`、`tool_layer/search_tool.py`、`data-pipeline/` 和
`data-persistence/`。

## 本地检查

当某次改动需要运行 Toolset 检查时，可在本目录执行：

```powershell
python -m unittest discover -s tests
```
