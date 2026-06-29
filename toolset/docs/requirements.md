# 工具集层需求文档

版本：v0.1  
模块：toolset / 工具集层  
状态：草稿  
适用范围：AI-QA-Assistant 工具集层当前已实现的检索能力与 Agent 调用契约  
编写依据：`需求文档编写规范 v1.0`、`toolset/README.md`、`tool_layer/search_tool.py`、`tests/test_search_tool.py`

## 文档说明

本文档只描述工具集层当前已经实现或已有明确接口约定的功能。每个需求小节只描述一个功能点或一个接口，便于后续进行需求一致性评审、RAG 检索和 Agent 任务分发。

## REQ-TOOLSET-001 统一检索工具入口

### 状态

明确

### 需求描述

工具集层应提供统一的 `SearchTool.search` 检索入口，供 Agent 层通过同一个接口调用不同检索模式。Agent 层不需要关心底层使用本地 JSONL、向量检索、BM25 还是 hybrid 融合检索。

### 关联接口

内部 Python 接口：`SearchTool.search(...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| query | string | 是 | 用户问题或检索关键词，不能为空 |
| top_k | integer | 否 | 返回结果数量，默认 5，范围 1-20 |
| mode | string | 否 | 检索模式，可选 `vector`、`bm25`、`hybrid`，默认 `hybrid` |
| filters | object | 否 | 过滤条件，当前支持 `doc_id`、`doc_ids`、`space`、`doc_type` |
| min_score | number | 否 | 最低相关性分数，默认 0.0 |
| trace_id | string | 否 | Agent 层传入的链路追踪 ID |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| doc_id | string | 文档唯一 ID |
| chunk_id | string | 文档块唯一 ID |
| chunk_index | integer | 文档块序号 |
| chunk_text | string | 文档块文本 |
| title | string | 文档标题 |
| score | number | 最终相关性分数 |
| vector_score | number | 向量检索分数 |
| bm25_score | number | BM25 检索分数 |
| source_url | string | 原始文档链接 |

### 异常情况

| 场景 | 错误类型 | 说明 |
| --- | --- | --- |
| query 为空 | RetrievalParameterError | 参数校验失败 |
| top_k 不在 1-20 范围内 | RetrievalParameterError | 参数校验失败 |
| mode 不是 `vector`、`bm25`、`hybrid` | RetrievalParameterError | 参数校验失败 |
| filters 不是 dict 或 None | RetrievalParameterError | 参数校验失败 |
| min_score 无法转换为数字 | RetrievalParameterError | 参数校验失败 |
| 底层检索异常 | RetrievalError | 检索失败 |

### 验收标准

- Agent 层可以通过 `SearchTool.search` 调用检索能力。
- `vector`、`bm25`、`hybrid` 三种模式都能通过同一个入口调用。
- 参数非法时抛出明确的参数错误。
- 检索成功但无结果时返回空列表 `[]`。
- 返回结果包含标准化字段，满足 Agent 层引用和回答生成需要。

### 待确认

- Agent 层最终传入的 `trace_id` 格式。
- 是否需要把该接口封装为 HTTP API。

## REQ-TOOLSET-002 本地 JSONL 检索后端

### 状态

明确

### 需求描述

工具集层应支持从本地 `chunks.jsonl` 文件加载文档块，并基于该文件提供本地检索能力，用于接口联调、算法验证和 Demo 环境运行。

### 关联接口

内部 Python 接口：`LocalJsonlSearchBackend(chunks_path=...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| chunks_path | string | 否 | JSONL 文档块文件路径，默认 `data/chunks.jsonl` |
| rrf_k | integer | 否 | RRF 融合参数，默认 60 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| chunks | array | 从 JSONL 加载的文档块列表 |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| chunks_path 不存在 | 返回空检索结果 | 后端加载空数据 |
| JSONL 某行格式非法 | 抛出异常并由 SearchTool 包装为 RetrievalError | 数据格式错误 |

### 验收标准

- 默认从 `data/chunks.jsonl` 加载检索数据。
- 文件不存在时不导致初始化失败。
- 每条非空 JSONL 行被解析为一个 chunk。
- 加载后的 chunk 可用于 vector、BM25 和 hybrid 检索。

### 待确认

- 正式测试数据集是否仍使用 `chunks.jsonl` 格式。
- JSONL 数据是否需要增加 schema 校验。

## REQ-TOOLSET-003 向量检索模式

### 状态

明确

### 需求描述

工具集层应支持 `vector` 检索模式。当前本地实现使用 TF-IDF cosine similarity 模拟向量检索入口，后续可替换为 Milvus 后端。

### 关联接口

内部 Python 接口：`SearchTool.search(mode="vector")`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| query | string | 是 | 检索问题或关键词 |
| top_k | integer | 否 | 返回结果数量 |
| filters | object | 否 | 文档过滤条件 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| results | array | 按语义相似度分数排序的文档块 |
| vector_score | number | 向量检索分数 |
| bm25_score | number | 固定为 0.0 |

### 异常情况

| 场景 | 错误类型 | 说明 |
| --- | --- | --- |
| query 无有效 token | 正常返回空列表 | 没有可计算相似度的内容 |
| 检索过程异常 | RetrievalError | 检索失败 |

### 验收标准

- `vector` 模式可以通过统一入口调用。
- 返回结果按 `score` 降序排列。
- 返回结果保留 `vector_score` 字段。
- 无匹配结果时返回空列表。

### 待确认

- Milvus 替换后的 collection 名称、embedding 维度和索引参数。

## REQ-TOOLSET-004 BM25 关键词检索模式

### 状态

明确

### 需求描述

工具集层应支持 `bm25` 检索模式，根据关键词匹配结果返回相关文档块。

### 关联接口

内部 Python 接口：`SearchTool.search(mode="bm25")`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| query | string | 是 | 检索问题或关键词 |
| top_k | integer | 否 | 返回结果数量 |
| filters | object | 否 | 文档过滤条件 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| results | array | 按 BM25 分数排序的文档块 |
| vector_score | number | 固定为 0.0 |
| bm25_score | number | BM25 检索分数 |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| 本地索引为空 | 返回空列表 | 没有可检索数据 |
| query 无有效 token | 返回空列表 | 没有可匹配关键词 |
| 检索过程异常 | 抛出 RetrievalError | 检索失败 |

### 验收标准

- `bm25` 模式可以通过统一入口调用。
- 返回结果按 `score` 降序排列。
- 返回结果保留 `bm25_score` 字段。
- 关键词命中文档块时应返回非空结果。

### 待确认

- 中文分词是否需要替换为专用分词器。

## REQ-TOOLSET-005 Hybrid RRF 融合检索

### 状态

明确

### 需求描述

工具集层应支持 `hybrid` 检索模式，将 vector 检索结果和 BM25 检索结果使用 RRF 算法进行融合，返回最终 Top-K 文档块。

### 关联接口

内部 Python 接口：`SearchTool.search(mode="hybrid")`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| query | string | 是 | 检索问题或关键词 |
| top_k | integer | 否 | 返回结果数量 |
| filters | object | 否 | 文档过滤条件 |
| min_score | number | 否 | 最低相关性分数 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| results | array | RRF 融合后的文档块列表 |
| score | number | 融合后的最终分数 |
| vector_score | number | vector 检索分数 |
| bm25_score | number | BM25 检索分数 |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| vector 和 BM25 均无结果 | 返回空列表 | 没有可融合结果 |
| 融合过程异常 | 抛出 RetrievalError | 检索失败 |

### 验收标准

- `hybrid` 模式可以通过统一入口调用。
- 融合结果按 `(doc_id, chunk_index)` 去重。
- 返回结果保留 `vector_score` 和 `bm25_score`。
- 最终结果按融合后的 `score` 降序排列。
- hybrid 结果不应简单等同于单一路径结果。

### 待确认

- RRF 参数是否需要配置化。
- hybrid 是否需要支持 vector 和 BM25 权重调整。

## REQ-TOOLSET-006 检索结果标准化

### 状态

明确

### 需求描述

工具集层应将底层后端返回的检索结果标准化，保证 Agent 层收到稳定字段结构。

### 关联接口

内部 Python 接口：`SearchTool.search(...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| raw_results | array | 是 | 后端返回的原始检索结果 |
| filters | object | 否 | 过滤条件 |
| min_score | number | 否 | 最低分数 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| normalized_results | array | 标准化后的检索结果 |

### 异常情况

| 场景 | 错误类型 | 说明 |
| --- | --- | --- |
| 结果缺少 doc_id | RetrievalError | 必要字段缺失 |
| 结果缺少 chunk_index | RetrievalError | 必要字段缺失 |
| score 非数字 | 正常兜底 | 按 0.0 处理 |

### 验收标准

- 如果底层没有 `chunk_id`，按 `{doc_id}::chunk_{chunk_index}` 自动生成。
- 如果底层没有 `title`，优先读取 `data/documents/{doc_id}.json` 中的标题。
- 如果标题仍不存在，使用 `doc_id` 兜底。
- 如果底层没有 `source_url`，优先读取文档元数据中的 `source_url`。
- 分数应归一化到可排序的数值范围。

### 待确认

- 是否需要返回页码、段落号、文档版本等引用字段。

## REQ-TOOLSET-007 检索过滤能力

### 状态

明确

### 需求描述

工具集层应支持按文档 ID、空间和文档类型过滤检索结果。

### 关联接口

内部 Python 接口：`SearchTool.search(filters=...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| doc_id | string | 否 | 指定单个文档 ID |
| doc_ids | array | 否 | 指定多个文档 ID |
| space | string | 否 | 文档所属空间 |
| doc_type | string | 否 | 文档类型 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| filtered_results | array | 满足过滤条件的检索结果 |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| filters 为 None | 不过滤 | 返回正常检索结果 |
| filters 类型非法 | 抛出 RetrievalParameterError | 参数错误 |
| 过滤后无结果 | 返回空列表 | 没有匹配数据 |

### 验收标准

- 支持按 `doc_id` 过滤。
- 支持按 `doc_ids` 过滤。
- 支持按 `space` 过滤。
- 支持按 `doc_type` 过滤。
- 过滤条件可以应用于 vector、BM25 和 hybrid 检索。

### 待确认

- 是否需要支持时间范围、文档来源系统和权限标签过滤。

## REQ-TOOLSET-008 检索日志与错误包装

### 状态

明确

### 需求描述

工具集层应在每次检索调用时记录基础检索日志，并在底层检索失败时抛出统一错误类型。

### 关联接口

内部 Python 接口：`SearchTool.search(...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| trace_id | string | 否 | 调用链路追踪 ID |
| mode | string | 是 | 检索模式 |
| top_k | integer | 是 | 返回结果数量 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| retrieval log | log line | 包含 trace_id、mode、top_k、results、latency |

### 异常情况

| 场景 | 错误类型 | 说明 |
| --- | --- | --- |
| 参数校验失败 | RetrievalParameterError | 直接抛出参数错误 |
| 后端异常 | RetrievalError | 包装为统一检索错误 |

### 验收标准

- 检索成功时记录 `trace_id`、`mode`、`top_k`、结果数量和耗时。
- 检索失败时抛出 `RetrievalError`。
- 参数错误不应被包装为普通后端异常。

### 待确认

- 是否需要在日志中增加 top scores。
- 是否需要输出结构化 JSON 日志。

## REQ-TOOLSET-009 Agent 引用字段支持

### 状态

明确

### 需求描述

工具集层返回的检索结果应包含 Agent 生成回答和前端展示引用所需字段。

### 关联接口

内部 Python 接口：`SearchTool.search(...)`

### 权限

仅系统内部模块调用。

### 输入

无额外输入。

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| title | string | 引用展示标题 |
| source_url | string | 可点击来源链接 |
| chunk_text | string | 引用片段 |
| doc_id | string | 文档 ID |
| chunk_id | string | 文档块 ID |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| title 缺失 | 使用文档元数据或 doc_id 兜底 | 保证字段存在 |
| source_url 缺失 | 返回空字符串 | 前端可不展示链接 |

### 验收标准

- 每条结果都包含 `title`。
- 每条结果都包含 `source_url` 字段。
- 每条结果都包含 `chunk_text`。
- Agent 层可以直接使用返回结果作为回答上下文。

### 待确认

- 前端引用展示是否需要额外字段，例如页码、章节名、更新时间。

## REQ-TOOLSET-010 本地单元测试覆盖

### 状态

明确

### 需求描述

工具集层应提供单元测试，覆盖统一入口、参数校验、返回字段标准化、异常包装、分数过滤和三种检索模式。

### 关联接口

命令行接口：`python -m unittest discover -s tests`

### 权限

开发者本地运行。

### 输入

无。

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| test result | text | 单元测试执行结果 |

### 异常情况

| 场景 | 处理方式 | 说明 |
| --- | --- | --- |
| 测试失败 | 返回失败用例 | 开发者修复后重新运行 |

### 验收标准

- 测试覆盖三种检索模式入口。
- 测试覆盖标准返回字段。
- 测试覆盖空结果返回。
- 测试覆盖参数校验。
- 测试覆盖后端异常包装。
- 测试覆盖 `min_score` 过滤。
- 测试覆盖 hybrid 去重。

### 待确认

- 是否需要增加与真实数据集的集成测试。

## REQ-TOOLSET-011 Milvus 后端替换能力

### 状态

待确认

### 需求描述

后续工具集层应支持将当前本地 TF-IDF vector 后端替换为 Milvus 向量数据库后端，同时保持 `SearchTool.search` 公共接口不变。

### 关联接口

内部 Python 接口：`SearchTool(backend=...)`

### 权限

仅系统内部模块调用。

### 输入

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| backend | object | 否 | 可替换检索后端，需要提供 `search(query, top_k, mode, filters)` 方法 |

### 输出

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| results | array | 与本地后端一致的标准化检索结果 |

### 异常情况

| 场景 | 错误类型 | 说明 |
| --- | --- | --- |
| Milvus 连接失败 | RetrievalError | 检索后端不可用 |
| collection 不存在 | RetrievalError | 检索配置错误 |
| embedding 维度不匹配 | RetrievalError | 向量数据错误 |

### 验收标准

- 替换 Milvus 后端后，Agent 层调用参数不变。
- Milvus 后端返回结果仍被标准化为统一字段结构。
- Milvus 后端异常被包装为 `RetrievalError`。

### 待确认

- Milvus 后端由 toolset 实现还是 data-persistence 层提供。
- embedding 模型、向量维度、collection 名称和部署地址。

## 提交前检查清单

- [x] 每个需求只有一个功能点或一个接口。
- [x] 每个需求都有唯一编号。
- [x] 每个需求都标明状态。
- [x] 接口类需求写明了内部接口或命令行接口。
- [x] 输入、输出、异常情况、权限已分开描述。
- [x] 验收标准可以被代码或测试验证。
- [x] 不明确内容已写入“待确认”。

