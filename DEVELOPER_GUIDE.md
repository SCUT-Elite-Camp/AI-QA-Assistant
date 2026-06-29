# RAGent 开发者指南 — 已就绪模块使用说明

本文档面向负责开发 `agent/`、`server/`、`frontend/`、`retrieval/search.py` 的团队成员，说明如何复用已实现的数据管线与存储层。

---

## 目录

- [1. 整体架构](#1-整体架构)
- [2. 环境准备](#2-环境准备)
- [3. 数据模型 (`models/`)](#3-数据模型-models)
- [4. 向量化 (`pipeline/embedder`)](#4-向量化-pipelineembedder)
- [5. 向量检索 (`storage/milvus_store`)](#5-向量检索-storagemilvus_store)
- [6. 关键词检索 (`retrieval/bm25_index`)](#6-关键词检索-retrievalbm25_index)
- [7. 文档元数据 (`storage/document_store`)](#7-文档元数据-storagedocument_store)
- [8. 文档解析 (`parsers/`)](#8-文档解析-parsers)
- [9. 离线管线 (`pipeline/process`)](#9-离线管线-pipelineprocess)
- [10. 检索层待办 (`retrieval/search.py`)](#10-检索层待办-retrievalsearchpy)
- [11. 各模块开发路径](#11-各模块开发路径)
- [附录：数据存储位置速查](#附录数据存储位置速查)

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    离线管线（已完成）                       │
│                                                         │
│  PDF/DOCX  →  parsers  →  chunker  →  embedder          │
│                              │            │              │
│                              ▼            ▼              │
│                      JSON 文件      Milvus 向量库         │
│                              │                           │
│                              ▼                           │
│                         BM25 索引                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    在线查询（部分待开发）                    │
│                                                         │
│  用户问题  →  search.py  →  agent  →  server  →  frontend │
│               (待开发)     (待开发)   (待开发)   (待开发)   │
└─────────────────────────────────────────────────────────┘
```

**关键原则：** 离线管线负责"入库"，在线查询负责"检索 + 生成"。两部分通过三个数据存储解耦——你不需要跑管线，只需要知道数据在哪里、怎么查。

---

## 2. 环境准备

### 2.1 启动 Milvus

```bash
docker-compose up -d
```

验证是否启动成功：

```bash
docker ps | grep milvus
```

### 2.2 安装 Python 依赖

```bash
uv sync
# 或
pip install -r requirements.txt
```

### 2.3 设置环境变量

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com/v1"   # 可选，兼容 DeepSeek 等
```

`OPENAI_API_KEY` 只在调用 `embed_texts()` 时需要（向量化用户 query）。如果你负责的是不需要调 embedding 的模块，可以暂不设置。

### 2.4 确保数据已入库

在开发在线查询链路之前，需要先跑一次离线管线，让 Milvus 和本地 JSON 中有数据：

```bash
python -m pipeline.process data/raws/测试空间
```

跑完后验证：

```bash
ls data/documents/          # 应该有若干 {doc_id}.json 文件
ls data/bm25_index.pkl      # BM25 索引文件
```

---

## 3. 数据模型 (`models/`)

所有数据模型定义在 `models/document.py`，已通过 `models/__init__.py` 导出。

```python
from models import Document, Chunk, ContentBlock, BlockType
```

### 3.1 `BlockType` 枚举

```python
BlockType.HEADING    # 标题
BlockType.PARAGRAPH  # 段落
BlockType.TABLE      # 表格
BlockType.LIST       # 列表
```

### 3.2 `ContentBlock` — 结构化内容块

```python
block = ContentBlock(
    block_type=BlockType.HEADING,
    level=2,                        # 标题层级 1-6
    text="第二章 系统设计",
    bold=False,
    italic=False,
)

# 方法
block.is_empty          # → bool, 是否无有效内容
block.to_markdown()     # → str, 渲染为 Markdown
```

### 3.3 `Chunk` — 文本分块

```python
chunk = Chunk(
    index=0,                              # 分块序号
    text="这是分块的文本内容...",           # 分块文本
    chunk_id="abc123_chunk_0",            # 全局唯一ID，格式: {doc_id}_chunk_{index}
)
```

### 3.4 `Document` — 完整文档

```python
doc = Document(
    doc_id="abc123...",          # MD5 哈希（文件绝对路径）
    title="产品手册",
    content="全文 Markdown...",   # 已渲染的全文
    space="测试空间",             # 来源文件夹名
    address="/abs/path/to/file.pdf",
    last_updated="2026-06-22T10:00:00+00:00",
    chunks=[...],                # list[Chunk]
    content_blocks=[...],        # list[ContentBlock]
    source_url="",
)

# 静态方法
doc_id = Document.generate_doc_id("/path/to/file.pdf")       # 计算 MD5
ts    = Document.generate_last_updated("/path/to/file.pdf")  # 文件修改时间

# 工厂方法
doc = Document.from_file_path(
    file_path="/path/to/file.pdf",
    content="全文文本...",
    content_blocks=[...],
)
```

> **注意：** 在线查询侧通常不需要构造 Document，只需要"反序列化"——见 [§7 文档元数据](#7-文档元数据-storagedocument_store)。

---

## 4. 向量化 (`pipeline/embedder`)

将文本转为 1536 维浮点向量。这是调用 Milvus 向量检索的**前置步骤**。

```python
from pipeline.embedder import embed_texts

vectors = embed_texts(
    texts=["用户的问题", "另一段文本"],
    model="text-embedding-3-small",     # 默认值，可省略
)
# → list[list[float]]，每个内层 list 长度为 1536

query_vector = vectors[0]  # 拿第一个去检索
```

**环境依赖：**
- `OPENAI_API_KEY` 必须设置
- `OPENAI_BASE_URL` 可选（默认 `https://api.openai.com/v1`）

**注意事项：**
- 支持批量调用，建议一次传多条以节省网络开销
- 向量维度固定为 1536，与 Milvus Collection schema 对应

---

## 5. 向量检索 (`storage/milvus_store`)

封装了 Milvus 的连接、建表、插入、搜索、删除操作。

```python
from storage.milvus_store import MilvusStore
```

### 5.1 初始化

```python
store = MilvusStore(host="localhost", port="19530")
```

构造函数自动调用 `connections.connect()`。如果 Milvus 未启动，这里会抛异常。

### 5.2 初始化 Collection

```python
collection = store.init_collection(
    collection_name="doc_chunks",   # 默认值
    dim=1536,                       # 向量维度，默认 1536
)
```

- 如果 Collection 已存在 → 直接加载
- 如果不存在 → 创建 schema + HNSW 索引（IP 内积度量，M=16, efConstruction=200）

**Collection Schema：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INT64 (auto) | 主键，自增 |
| `embedding` | FLOAT_VECTOR(1536) | 向量 |
| `chunk_id` | VARCHAR(256) | 全局分块 ID |
| `chunk_text` | VARCHAR(65535) | 分块原始文本 |
| `doc_id` | VARCHAR(128) | 所属文档 ID |
| `chunk_index` | INT32 | 分块序号 |
| `source_url` | VARCHAR(512) | 来源链接 |

### 5.3 向量搜索（这是在线查询的核心入口）

```python
from pipeline.embedder import embed_texts

# 1. 向量化用户问题
query_vector = embed_texts(["用户的问题"])[0]

# 2. 向量检索
hits = store.search_similar(
    query_vector,
    top_k=5,
    doc_ids_filter=None,              # 可选，限定文档范围: ["doc_id_1", "doc_id_2"]
    collection_name="doc_chunks",     # 默认值
)

# 3. 解析结果
for hit in hits:
    entity = hit.entity
    chunk_id   = entity.get("chunk_id")      # str
    chunk_text = entity.get("chunk_text")    # str
    doc_id     = entity.get("doc_id")        # str
    chunk_idx  = entity.get("chunk_index")   # int
    source_url = entity.get("source_url")    # str
    score      = hit.distance                # float, 内积越大越相似
```

**返回值说明：**
- `hits` 是 `pymilvus.Hits` 对象，可迭代
- `hit.distance` 是内积相似度（IP 度量），值越大越相似
- `hit.entity.get(field)` 获取输出字段

### 5.4 其他操作

```python
# 插入（通常只在离线管线中使用）
store.insert_chunks(
    embeddings=[[0.1, 0.2, ...], ...],
    chunk_ids=["abc_chunk_0", ...],
    chunk_texts=["文本1", ...],
    doc_ids=["abc", ...],
    chunk_indices=[0, 1, ...],
    source_urls=["", ...],            # 可选
)

# 删除 Collection（谨慎使用）
store.delete_collection("doc_chunks")
```

---

## 6. 关键词检索 (`retrieval/bm25_index`)

基于 `rank_bm25.BM25Okapi` + `jieba` 分词的中文关键词检索。

```python
from retrieval.bm25_index import BM25Index
```

### 6.1 加载索引

```python
bm25 = BM25Index()

# 方式一：从已持久化的 pickle 文件加载（推荐，快速）
bm25.load("data/bm25_index.pkl")
# 或使用工厂方法
bm25 = BM25Index.load_from_file("data/bm25_index.pkl")

# 方式二：从 data/documents/ 目录下的 JSON 重新构建（较慢）
bm25.build_from_documents()
```

### 6.2 关键词搜索

```python
results = bm25.search("如何配置 Milvus?", top_k=5)
# → list[dict]，每项包含：
#   chunk_id    - 全局分块 ID
#   doc_id      - 所属文档 ID
#   chunk_index - 分块序号
#   text        - 分块文本
#   score       - BM25 分数（float）
```

### 6.3 属性

```python
bm25.chunk_count   # → int, 索引中的分块总数
bm25.is_empty      # → bool, 索引是否为空
```

### 6.4 默认路径

```python
BM25Index.default_index_path()   # → "data/bm25_index.pkl"
```

---

## 7. 文档元数据 (`storage/document_store`)

本地 JSON 文件的读写，用 `doc_id` 做 key。当你从 Milvus/BM25 拿到 `doc_id` 后，用它来查完整文档信息。

```python
from storage.document_store import load_document, save_document, delete_document
```

### 7.1 加载文档

```python
doc = load_document("abc123...")   # doc_id 来自检索结果
if doc is None:
    print("文档不存在")

# doc 是一个 dict，字段与 models.Document 对应：
title     = doc["title"]           # str
content   = doc["content"]         # str, 全文 Markdown
space     = doc["space"]           # str, 来源文件夹
address   = doc["address"]         # str, 原始文件绝对路径
chunks    = doc["chunks"]          # list[dict], 每个包含 index/text/chunk_id
doc_id    = doc["doc_id"]          # str
```

### 7.2 典型使用场景：从检索结果补全上下文

```python
from storage.milvus_store import MilvusStore
from storage.document_store import load_document
from pipeline.embedder import embed_texts

store = MilvusStore()
query_vector = embed_texts(["用户问题"])[0]
hits = store.search_similar(query_vector, top_k=5)

context_chunks = []
seen_docs = set()

for hit in hits:
    doc_id = hit.entity.get("doc_id")
    chunk_text = hit.entity.get("chunk_text")

    # 如果需要展示文档标题等信息，查 JSON
    if doc_id not in seen_docs:
        doc = load_document(doc_id)
        if doc:
            print(f"来源文档: {doc['title']}")
        seen_docs.add(doc_id)

    context_chunks.append(chunk_text)
```

### 7.3 存储路径

```python
from storage.document_store import DOCS_DIR
# → "<项目根>/data/documents/"
```

---

## 8. 文档解析 (`parsers/`)

```python
from parsers import parse_file, get_parser, supported_extensions

# 获取支持的文件类型
exts = supported_extensions()   # → [".pdf", ".docx"]

# 根据扩展名获取解析器
parser = get_parser(".pdf")     # → PDFParser 实例 或 None

# 一键解析
doc = parse_file("/path/to/file.pdf")
# → Document 对象（含 content、content_blocks 等，chunks 为空）
```

> **注意：** `parse_file()` 只负责解析，不包含分块和向量化。完整的"解析→分块→向量化→入库"流程请用 `process_folder()`。

---

## 9. 离线管线 (`pipeline/process`)

```python
from pipeline.process import process_folder

docs = process_folder(
    folder_path="data/raws/测试空间",
    chunk_size=500,                # 默认
    overlap=100,                   # 默认
    milvus_host="localhost",       # 默认
    milvus_port="19530",           # 默认
)
# → list[Document]，每个 Document.chunks 已填充

# 也可以命令行调用：
# python -m pipeline.process data/raws/测试空间 --chunk-size 500 --overlap 100
```

**`process_folder` 做了什么：**
1. 扫描文件夹中的所有 PDF/DOCX
2. 对每个文件：`parse_file()` → `chunk_from_blocks()` → `embed_texts()`
3. `save_document()` 写入 JSON
4. `MilvusStore.insert_chunks()` 写入 Milvus
5. 全部文件处理完后 `BM25Index.build_from_documents()` 重建 BM25 索引

> **幂等性：** `doc_id` 基于文件绝对路径的 MD5，重复跑同一文件夹不会产生重复数据。

---

## 10. 检索层待办 (`retrieval/search.py`)

这是当前 **优先级最高的缺失模块**。`agent/` 的开发者不应该直接分别调 Milvus 和 BM25 然后自己写融合——应该由一个统一入口封装。

### 10.1 期望接口

```python
from retrieval.search import search

results = search(
    query="用户问题",
    top_k=5,
    mode="hybrid",          # "vector" | "bm25" | "hybrid"
    doc_ids_filter=None,    # 可选，限定文档范围
)
# → list[dict]，每项：
#   {
#       "chunk_id": "...",
#       "doc_id": "...",
#       "chunk_text": "...",
#       "chunk_index": 0,
#       "score": 0.95,            # RRF 融合后的最终分数
#       "vector_score": 0.92,     # 向量相似度
#       "bm25_score": 8.5,        # BM25 分数
#       "title": "文档标题",       # 从 JSON 补全
#       "source_url": "...",
#   }
```

### 10.2 需要做的事

1. 调用 `embed_texts()` 将 query 向量化
2. 并行（或串行）调用 `MilvusStore.search_similar()` 和 `BM25Index.search()`
3. 用 **RRF (Reciprocal Rank Fusion)** 融合两路结果
4. 去重（同一 chunk 可能两路都命中）
5. 用 `load_document()` 补全 `title` 等信息
6. 按最终分数降序返回

### 10.3 RRF 公式参考

```
RRF_score(chunk) = Σ 1 / (k + rank_i)
```

其中 `k` 是平滑常数（通常取 60），`rank_i` 是该 chunk 在第 i 路检索结果中的排名（从 1 开始）。

---

## 11. 各模块开发路径

按依赖关系，建议的开发顺序如下：

```
retrieval/search.py   ──→   agent/   ──→   server/   ──→   frontend/
```

### 11.1 `retrieval/search.py` 开发者

**依赖（全已就绪）：**
- `storage.milvus_store.MilvusStore`
- `retrieval.bm25_index.BM25Index`
- `pipeline.embedder.embed_texts`
- `storage.document_store.load_document`

**要产出：** 统一的 `search()` 或 `SearchTool` 类

**参考规格：** `plan.md` 第 3.1.1 节

### 11.2 `agent/` 开发者

**依赖：**
- `retrieval/search.py` 的 `search()` —— **先确保它已实现**
- `agent/llm.py` —— 你自己实现，封装 OpenAI 兼容的 LLM 调用
- `agent/prompt.py` —— 你自己实现，组装 prompt（包含检索到的上下文 + 幻觉抑制指令）

**要产出：** `RAGAgent` 类，提供 `query(query, session_id, stream)` 方法

**典型流程：**
```
1. search(query) → 检索结果
2. 组装 prompt（系统提示 + 上下文 chunks + 用户问题）
3. 调用 LLM 流式生成
4. 返回 {trace_id, answer, citations}
```

### 11.3 `server/app.py` 开发者

**依赖：** `agent/` 的 `RAGAgent`

**要产出：** Flask 应用，提供 SSE 流式接口

**典型路由：**
```
POST /api/query
  Body: { "query": "...", "session_id": "...", "stream": true }
  Response: SSE 事件流
```

### 11.4 `frontend/` 开发者

**依赖：** `server/` 的 HTTP API

**要产出：** Vue 3 SPA 聊天界面

**不直接依赖任何 Python 代码**，只需对接 HTTP/SSE 接口。

---

## 附录：数据存储位置速查

| 存储 | 路径/地址 | 格式 | 读写模块 |
|------|----------|------|---------|
| Milvus 向量库 | `localhost:19530`，Collection `doc_chunks` | HNSW 索引 | `storage.milvus_store` |
| 文档 JSON | `./data/documents/{doc_id}.json` | JSON | `storage.document_store` |
| BM25 索引 | `./data/bm25_index.pkl` | Pickle | `retrieval.bm25_index` |
| 原始文件 | `./data/raws/` | PDF/DOCX | `parsers/` |

### 常用 import 速查

```python
# 数据模型
from models import Document, Chunk, ContentBlock, BlockType

# 向量化
from pipeline.embedder import embed_texts

# 向量检索
from storage.milvus_store import MilvusStore
store = MilvusStore()
store.init_collection()
hits = store.search_similar(query_vector, top_k=5)

# 关键词检索
from retrieval.bm25_index import BM25Index
bm25 = BM25Index.load_from_file("data/bm25_index.pkl")
results = bm25.search(query, top_k=5)

# 文档元数据
from storage.document_store import load_document, DOCS_DIR
doc = load_document(doc_id)

# 文档解析（按需）
from parsers import parse_file, get_parser, supported_extensions

# 离线管线（按需）
from pipeline.process import process_folder

# 分块（按需）
from pipeline.chunker import chunk_text, chunk_from_blocks
```
