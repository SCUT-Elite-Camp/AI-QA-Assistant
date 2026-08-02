# 数据处理流水线文档

## 架构总览

```
原始文档 (PDF/DOCX)
    │
    ▼
┌─────────────────────┐
│   1. 文档解析        │  parsers/registry.py  → PDFParser / DocxParser
│      → Document      │  提取全文 + ContentBlock 结构化块
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   2. 语义分段        │  segmenter/similarity_segmenter.py
│      → Segments      │  LightMem B₂ 算法：句子 embedding → 相似度断点
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   3. 预压缩 (可选)   │  precompressor/ → EntropyCompressor / LLMLingua2
│      → 压缩文本      │  降噪去冗余，提高检索信噪比
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   4. 文本切片        │  pipeline/chunker.py
│      → Chunks        │  内容感知切片 (ContentBlock) 或滑窗切片
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   5. 向量化          │  pipeline/embedder.py
│      → Embeddings    │  BGE-small-en-v1.5 (384d) via ModelScope
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   6. 知识卡片        │  knowledge_cards/card_builder.py
│      → Cards         │  Zettelkasten 原子知识单元 + 图谱链接
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│   7. 存储                                │
│   ├─ Milvus (向量检索)                   │
│   ├─ BM25 索引 (关键词检索)              │
│   └─ SQLite (卡片关系图)                 │
└─────────────────────────────────────────┘
```

---

## 1. 语义分段器 (`segmenter/`)

### 原理

LightMem B₂ 相似度分段算法，不依赖 LLM，仅使用句子级 embedding：

```
句子 → split_sentences() → merge_short_sentences(min_chars=15)
      → BGE encode → [emb₁, emb₂, ..., embₙ]
      → cos_sim(embᵢ, embᵢ₊₁) < threshold → 标记为边界
      → 边界间句子组 → SemanticSegment
      → 段 embedding 与已有 topic 均值比较 → 分配 topic_id
```

### 核心类: `SimilaritySegmenter`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `similarity_threshold` | 0.65 | 相邻句余弦相似度低于此值则切分 |
| `topic_reuse_threshold` | 0.80 | 段与已有 topic 相似度高于此值则复用 topic_id |
| `min_sentences` | 2 | 每段最少句子数 |

### 使用示例

```python
from segmenter.similarity_segmenter import SimilaritySegmenter

segmenter = SimilaritySegmenter(
    similarity_threshold=0.65,
    topic_reuse_threshold=0.80,
)

segments = segmenter.segment(
    text="Machine learning is...\nDocker containers...",
    doc_id="doc_001"
)

for seg in segments:
    print(f"topic={seg.topic_id}, sentences={len(seg.sentences)}")
    print(f"text: {seg.text[:100]}...")
```

### Topic 聚类

同一文档中语义相近的段被分配到相同的 `topic_id`，支持跨文档的主题追踪。

---

## 2. 知识卡片系统 (`knowledge_cards/`)

### 数据模型

```
KnowledgeCard (原子知识单元)
├── card_id          : 唯一标识
├── content          : 原始文本（不可变，保证可追溯）
├── keywords         : LLM 提取的检索关键词
├── tags             : 分类标签 (fact/definition/process/...)
├── context          : LLM 生成的语义描述（可变，演化时更新）
├── embedding        : 384d 向量 (content+keywords+tags+context)
├── links            : 关联卡片 ID 列表
├── source_segments  : 来源段落 ID
├── retrieval_count  : 检索热度计数
├── evolution_history: 演化审计记录
└── is_evolved       : 是否已被后续信息更新

CardLink (卡片关联)
├── source_id / target_id : 双向连接
├── link_type              : elaborates/contradicts/supports/precedes/example_of
├── strength               : 关联强度 0~1
└── reason                 : 关联理由

EvolutionRecord (演化审计)
├── trigger_card_id : 触发演化的卡片
├── field_changed   : 被修改的字段
├── old_value/new_value : 变更前后值
├── evolution_type  : evolve/conflict/expand/new
└── reason          : 演化理由
```

### 标签枚举

| 标签 | 含义 |
|------|------|
| `fact` | 事实陈述 |
| `decision` | 决策/决议 |
| `constraint` | 约束条件 |
| `event` | 事件 |
| `definition` | 定义/术语 |
| `process` | 流程/步骤 |
| `data_point` | 数据点 |

### 使用示例

```python
from knowledge_cards.schemas import (
    KnowledgeCard, CardLink, EvolutionRecord,
    CardTag, LinkType, EvolutionAction
)

# 创建卡片
card = KnowledgeCard(
    content="Machine learning uses statistical methods...",
    doc_id="doc_001",
    keywords=["ML", "statistical", "learning"],
    tags=[CardTag.FACT.value, CardTag.DEFINITION.value],
    context="Definition of machine learning approach",
)

# 卡片演化
record = EvolutionRecord(
    trigger_card_id="card_xxx",
    field_changed="context",
    old_value=card.context,
    new_value="Updated context with new details",
    evolution_type=EvolutionAction.EXPAND,
    reason="New information from related document",
)
card.evolution_history.append(record)
card.context = record.new_value
card.is_evolved = True

# 关联卡片
link = CardLink(
    source_id=card_a.card_id,
    target_id=card_b.card_id,
    link_type=LinkType.ELABORATES.value,
    strength=0.85,
    reason="Card B elaborates on concepts in Card A",
)
```

### 组合文本 (用于 embedding)

```python
def combined_text(self) -> str:
    return "\n".join([
        f"content: {self.content}",
        f"keywords: {', '.join(self.keywords)}",
        f"tags: {', '.join(self.tags)}",
        f"context: {self.context}",
    ])
```

---

## 3. 预压缩器 (`precompressor/`)

### 工厂接口

```python
from precompressor.compressor_factory import create_compressor

# 三种压缩策略
comp = create_compressor("entropy_compress")  # CausalLM 自信息过滤 (GPU 推荐)
comp = create_compressor("llmlingua2")        # BERT token 分类器
comp = create_compressor("none")              # 不压缩

# 统一接口
compressed = comp.compress(text, compress_rate=0.6)  # 保留 60%
```

### 两种实现

| 实现 | 方法 | 模型 | 适用场景 |
|------|------|------|----------|
| `EntropyCompressor` | CausalLM 词级自信息过滤 | GPT-2 | 英文文本，GPU 推理 |
| `LLMLingua2Compressor` | BERT token 级分类 | llmlingua-2-bert-multilingual | 多语言，CPU 推理 |

### 抽象基类

```python
class BasePreCompressor:
    def compress(self, text: str, compress_rate: float = 0.6) -> str:
        """压缩文本，保留 compress_rate 比例的关键信息"""
        ...

    def compress_blocks(self, blocks: list[str], compress_rate: float = 0.6) -> list[str]:
        """批量压缩文本块"""
        ...
```

---

## 4. 文档解析与切片

### 支持的格式

| 格式 | 解析器 | 特性 |
|------|--------|------|
| `.pdf` | `PDFParser` (PyMuPDF) | 提取文本 + ContentBlock 结构 |
| `.docx` | `DocxParser` (python-docx) | 段落/表格/样式信息 |

### ContentBlock 感知切片

```python
from parsers.registry import parse_file
from pipeline.chunker import chunk_from_blocks

doc = parse_file("document.pdf")

# ContentBlock 结构: [Block(block_type="paragraph", level=0, text="..."), ...]
if doc.content_blocks:
    chunks = chunk_from_blocks(doc.content_blocks, doc.doc_id, chunk_size=500, overlap=100)
else:
    chunks = chunk_text(doc.content, doc.doc_id, chunk_size=500, overlap=100)
```

---

## 5. 增量处理 (`auto_process.py`)

### 自动检测新增/修改

```python
from pipeline.auto_process import auto_process_raws

# 扫描 data-persistence/data/raws/ → 比对 JSON 时间戳 → 仅处理变更文件
auto_process_raws()
```

增量逻辑：
1. 扫描 `raws/` 目录下所有 PDF/DOCX
2. 如果对应 `{doc_id}.json` 不存在 → 新文件，处理
3. 如果 JSON 存在但 `last_updated` 不匹配 → 已修改，重新处理
4. 否则 → 跳过

### 命令行用法

```bash
python -m pipeline.auto_process
python -m pipeline.auto_process --chunk-size 800 --overlap 200
python -m pipeline.process data/raws/测试数据  # 处理指定目录
```

---

## 6. 向量化与存储

### Embedding 模型

- **模型**: BAAI/bge-small-en-v1.5
- **维度**: 384
- **下载**: 首次自动从 ModelScope 下载 (~95MB)，缓存于 `~/.cache/modelscope/`

### 存储后端

| 存储 | 用途 | 位置 |
|------|------|------|
| Milvus | 向量相似度检索 | `localhost:19530` |
| JSON 文件 | 文档元数据 | `data-persistence/data/documents/` |
| BM25 索引 | 关键词检索 | `data-persistence/data/bm25_index.pkl` |
| SQLite | 知识卡片关系图 | `data-persistence/storage/` |

---

## 7. 模块依赖

```
data-pipeline/
├── pipeline/          # 核心流水线
│   ├── process.py     # 全量处理入口
│   ├── auto_process.py # 增量处理入口
│   ├── chunker.py     # 文本切片
│   └── embedder.py    # BGE 向量化
├── parsers/           # 文档解析器
│   ├── registry.py    # 解析器注册 (自动路由)
│   ├── pdf_parser.py  # PDF → ContentBlock
│   └── docx_parser.py # DOCX → ContentBlock
├── segmenter/         # 语义分段
│   ├── base.py        # SemanticSegment 数据模型
│   ├── similarity_segmenter.py  # LightMem B₂ 算法
│   └── sentence_utils.py       # 分句 + 短句合并
├── precompressor/     # 预压缩
│   ├── base.py        # 抽象接口
│   ├── compressor_factory.py   # 工厂方法
│   ├── entropy_compress.py     # CausalLM 压缩
│   └── llmlingua2.py  # BERT 压缩
├── knowledge_cards/   # 知识卡片
│   ├── schemas.py     # KnowledgeCard / CardLink / EvolutionRecord
│   ├── card_builder.py   # LLM 卡片构建
│   ├── card_retriever.py # 卡片检索
│   ├── card_linker.py    # 卡片关联
│   ├── card_evolver.py   # 卡片演化
│   ├── card_store.py     # SQLite 存储
│   └── stm_buffer.py     # 短期记忆缓冲
└── models/            # 数据模型
    └── document.py    # Document / Chunk
```

---

## 8. 验证结果 (2026-07-27)

| 测试项 | 状态 | 结果 |
|--------|------|------|
| PDF 解析 | ✅ | 41 字符 → 1 个 ContentBlock |
| 语义分段 | ✅ | 12 句跨 4 主题 → 4 段，4 个 topic |
| 文本切片 | ✅ | 1 chunk (测试文档过短) |
| BGE 向量化 | ✅ | 384d 向量 → Milvus 写入成功 |
| BM25 索引 | ✅ | 1 个分块索引 |
| 知识卡片 | ✅ | 创建 + 演化 + 关联 链路完整 |
| 预压缩器 | ✅ | 工厂 + 接口验证通过 |
| 增量检测 | ✅ | 时间戳比对跳过已处理文档 |
