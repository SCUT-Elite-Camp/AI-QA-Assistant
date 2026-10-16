# Toolset 工具层

## 2026-10-16 English semantic reranking

`SearchTool.search` and `search_direct` share a local cross-encoder stage after
scope filtering and evidence normalization. Each active retrieval channel requests
20 candidates; Hybrid uses RRF to select a 20-item pool, suppresses same-document,
same-version duplicate text, and ranks query/passage pairs to return TopK (default 5).
Personal Library uses the same `retrieval.reranker` component. Fast mixed enterprise/
personal retrieval obtains candidates from both sources and reranks one bounded
cross-source pool; attachment file context remains separately scoped.

Default model: `cross-encoder/ms-marco-MiniLM-L6-v2`, pinned local installation at
revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. Default weight directory is
`data-persistence/models/ms-marco-MiniLM-L6-v2`; set `RERANK_MODEL_PATH` to relocate.
Install with `huggingface_hub.snapshot_download` using that repo ID and revision
before starting services. Requests use local files only, never remote model code.

`RERANK_ENABLED=true`, `RERANK_CANDIDATE_K=20`, `RERANK_DEVICE=cpu` configure the stage.
`RERANK_CPU_THREADS=4` configures Torch CPU threads once on model load, also
affecting other local Torch models in that process. Weights are cached; request
texts and authorization grants are not. A request-local ContextVar callback
validates candidate source permission/version/hash before ranking, propagates
through the tool thread pool, and never degrades authorization failures into
ranking fallbacks. Unknown/stale enterprise chunk lineage is excluded before inference.
Rows retain original `score` for existing retrieval thresholds and provenance;
`retrieval_score`, `rerank_score`, `retrieval_rank`, `rerank_rank`, and
`rerank_status` describe ordering. Relevance logits are not truth probabilities.
Missing/failed weights produce an explicit `RERANK_DEGRADED` log and
`rerank_status=degraded` on returned rows, with the fused ordering preserved.
Set `RERANK_ENABLED=false` for a separately labeled baseline. Runtime capability
tests must use actual installed weights; ordinary unit tests explicitly disable
them or inject deterministic rankers.

TopK counts primary hits. `RETRIEVAL_CONTEXT_ENABLED=true` also attaches original
previous/next same-section chunks, bounded to 2,000 characters each and 4,000
additional characters per tool response. These retain independent chunk IDs,
versions and hashes; adapters emit primary hits first, then contextual evidence.
They are neither concatenated into a new purported source excerpt nor silently
treated as additional ranked hits. Fast's overall context budget remains in force.

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

Fast 通过 `SearchTool.search_direct()` 用原问题执行一次检索，沿用同一参数校验、
权限过滤、检索后端与证据规范化；跳过标题/日期范围推断及章节扩展。
Thinking 继续使用 `search()` 的既有能力。内部执行标记不暴露给模型、不提供授权。

Fast 的 `read_attachment_context` 按受信任文件作用域读取已解析文本/OCR及原图，
不调用独立视觉模型。原图带当前文件 hash/version 引用，并合入最终答案的同一次请求；
项目不再提供独立视觉模型；`inspect_attachment`、本地 VLM 加载/推理与其依赖配置已删除。
Thinking 附件工具只读取文档文字、OCR 和表格证据。

2026-10-15：附件证据检索由 `tool_layer.attachment_tools.search_attachment_evidence` 执行，
个人库检索与候选融合由 `tool_layer.search_library_tool` 执行。工具和 Agent 文件接口直接调用
这些函数，不再使用 Pipeline 的 `private_tools` 分发层或 `PrivateRetrieval` 类。
个人库先过滤 owner、知识库和活动版本，再调用公共 `MilvusStore`；数据集合与企业库隔离。

文档名称匹配逻辑由 `tool_layer.document_matching` 维护；章节元数据使用 Pipeline 的
`pipeline.documents.sections`，存储路径与文件配置通过 Data Persistence 的公开接口读取。

Toolset 不在模块导入时创建全局注册表。Agent 在实例化时创建并持有一个 `ToolRegistry`，再通过只读适配器访问它；需要默认工具时直接使用 `ToolRegistry()`。

2026-10-09 整合中 Chat 与 Research 共用企业搜索/原文读取。工具保留 `source_version`、正文 `content_hash`、locator 和 `evidence_ref`，Agent 核对文本属于同一权威原文，不能将旧索引片段绑定新版本。private 工具 HMAC/owner/KB/作用域约束见[跨层契约](../docs/access-evidence/access-evidence-integration.md)，携内部凭据的 HTTP 请求拒绝重定向。Wiki 导航元数据因自身访问证明不足暂被隔离。

## 文档目录与批量全文读取

Thinking 的补充取证流程为 `search_documents` TopK → 判断证据是否充分 →
`find_documents` 列文档目录 → `get_document(doc_ids=[...])` 批量读取全文。
已知文档 ID 或需要通读时可以直接读取。Fast 继续执行原问题单次检索。

- `find_documents(query?, filters?, offset=0, top_k=5)`：省略 query 可列目录；
  返回 `documents/result_count/total_documents/has_more/next_offset`。目录包含文档
  ID、标题、类型及来源版本等元数据；匹配摘要只用于选择文档，不生成引用证据。
- `get_document(doc_ids=[...])`：一次读取 1–20 个文档 ID，重复 ID 去重；返回
  `documents/errors/result_count`。每篇包含 `content` 完整解析文本和带来源元数据的
  `chunks`，不存在的文档单列错误。没有正文时才按原块序号重建文本。
  不再接受 `doc_id/offset/limit/expected_version/expected_hash`，不分页或静默截断全文。

Agent 在批量读取前逐篇核对当前权限，目录和读取所得的每个来源都进入依赖复核；
选文档后发生版本变化或撤权会阻止后续模型调用。正文块保留版本、hash 和引用定位。
`navigation_tools.py`、章节浏览/章节内再检索入口及其专用实现已删除。
私有库的 outline/search-scoped 后端接口及专用章节向量索引也已删除；
`HIERARCHICAL_NAVIGATION_ENABLED` 和 `ATTACHMENT_SECTION_*` 配置不再使用。
Pipeline 的结构化切块和已有来源定位继续保留，已有索引/集合未做物理清理。

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
英文分析器在实例化时要求 NLTK 和 scikit-learn；依赖缺失或无法导入时明确报错并给出
`python -m pip install -r requirements.txt` 安装提示，不再替换词干算法或停用词表。
只导入检索模块不加载这些依赖。分析器版本已更新为
`english_regex_snowball_sklearn_stopwords_v2`：旧版索引无法判断是否由降级规则生成，
加载时会提示重建。升级时保留原索引并另外构建、验证新索引，本次代码修改不会自动覆盖运行数据。
大纲导航则从活动文档记录中读取 Section 元数据。向量检索使用配置的 Embedding 提供方和 Milvus。
相关实现位于 `retrieval/`、`tool_layer/search_tool.py`、`data-pipeline/` 和
`data-persistence/`。

## 附件解析工具

`tool_layer.parse_attachment_tool.parse_attachment_context(path, source_id, store)` 只调用 Pipeline 统一解析入口、把结果交给 Data Persistence，并返回文本上下文和定位信息。Toolset 不实现格式解析、分块、embedding 或附件索引。

Pipeline 的 `pipeline.files.parsing.parse_document(path)` 返回结构化 `list[Document]`；`parse_context(path, source_id)` 返回 `context/items/documents`，解析阶段不写入索引。Data Persistence 原子保存解析快照并安排个人库摄取任务，Pipeline 后续复用 `prepare_ingestion_chunks` 分块并写入私有集合。对话附件本身只提供上下文，不再维护另一份临时向量索引。

Web 上传同时建立 owner 私有的个人库文档与版本，复用同一次解析结果；附件过期或删除不删除个人库副本。Web 后台同步索引状态并执行现有活动版本 CAS，无需打开资料库触发。上传、读取和内部任务由 Agent 进程托管于 `/private-files`，不再启动独立服务或使用 `ATTACHMENT_SERVICE_URL`。原有数据目录、加密 key、私有集合继续沿用；权限、Chat/Topic 绑定与证据版本/hash 检查保持有效。

## 本地检查

当某次改动需要运行 Toolset 检查时，可在本目录执行：

```powershell
python -m unittest discover -s tests
```
