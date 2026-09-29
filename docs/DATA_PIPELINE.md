# 数据处理流水线文档

## PDF 结构化入库（当前实现）

PDF 解析由 `data-pipeline/parsers/pdf_parser.py` 的 `PDFParser` 实现，公共路由入口是
`parsers.registry.parse_file(path)`。当前 PDF 链路包含六项改进：

1. 每个正文块保留稳定 `block_id`、页码、bbox、字体/字号、旋转角度、来源和置信度；
2. 根据 span 坐标识别常见双栏并重建确定性的阅读顺序；
3. 对空、稀疏、乱码或图片覆盖的页面按需回退到通用 OCR；
4. 按跨页重复内容动态识别页眉页脚，不再固定裁掉页面上下 15%；
5. `accepted` 表格按 bbox 重叠阈值排除正文；`review` 表格及其 `ContentBlock`/`TableArtifact`
   仍序列化到文档 JSON 供诊断，但不进入 `Document.content`、结构化 chunk 或 embedding；
   `rejected` 表格丢弃；
6. 结构感知压缩和切块保留标题与表格边界，并把来源追踪信息写入 Milvus。

通用 OCR 使用 PyMuPDF 的 `get_textpage_ocr()`，需要本机 Tesseract 及 `chi_sim`/`eng`
语言数据；通过 `PDF_OCR_LANGUAGES` 可覆盖语言（默认 `chi_sim+eng`）。程序只选择实际
已安装的请求语言；若请求语言都缺失，则优先降级到 `eng`，再降级到首个已安装语言。
`PDF_OCR_DPI` 可在 72–600 间调整（默认 300）；普通笔记本建议先用 220–240，速度和
内存占用更低。Tesseract 或全部语言数据缺失、OCR 失败时保留原生文本并写入诊断，
不阻断文档处理。混合页面会保留可靠的原生文字，只补入非重叠 OCR 区域并去掉重复块。
项目不会自动安装 Tesseract 或语言包。Camelot/GMFT 以及
`requirements-table-ocr.txt` 中的 PaddleOCR/PaddlePaddle 都是可选的表格后端；PaddleOCR
仅用于表格结构恢复，不是通用正文 OCR 的依赖。

```powershell
$env:PDF_OCR_DPI = "220"
$env:PDF_OCR_LANGUAGES = "chi_sim+eng"
```

主管线共用 `pipeline.structured_ingestion.prepare_ingestion_chunks()`：
`process_folder_amem()`（全量/A-MEM）和 `auto_process_raws()`（增量）均经由它生成
chunk。只有 `chunk_type == "text"` 的块进行语义分割；`table`/`table_row` 直接保留。
`ContentBlock` 仍只表示单页内容；`Chunk.page_regions` 与 `TableArtifact.page_regions` 按页
保存真实贡献区域的 bbox、正文块/表格 ID、来源和置信度。单页 chunk 继续兼容旧的
`page_number`/`bbox` 标量字段；多页 chunk 的标量页码和 bbox 为空（Milvus 页码写 0），
完整来源页码写入 `metadata_json.source_pages`，精确坐标写入
`metadata_json.page_regions`。没有可靠 bbox 的来源页仍保留在 `source_pages`，但不会伪造
`page_regions`。

切片同时保存两种文本视图：`Chunk.index_text` 是去除标题井号、粗体符号和 Markdown
表格语法后的语义文本，用于切片长度计算、语义分段、向量化和 BM25；
`Chunk.markdown_text` 用于大模型上下文和前端展示。既有 `Chunk.text` 继续等同于
`markdown_text`，旧 JSON 缺少新字段时会从 `text` 自动补齐，因此不需要迁移存量文档。
新增字段不改变 Milvus schema；但历史向量和 BM25 仍基于旧文本，若要让存量数据获得
纯文本索引收益，需要重新解析或执行安全重建。

`doc_chunks` 新建集合必须包含 `chunk_type`、`block_id`、`table_id`、`page_number`、
`bbox_json`、`metadata_json` 六个来源字段（以及既有字段）。Milvus 不支持在线补齐既有
集合字段；检测到旧 schema 时管线会明确报错。先运行默认不修改数据的预检，再在维护窗口
使用精确确认口令执行：

```powershell
& .venv\Scripts\python.exe scripts\safe_reindex.py
& .venv\Scripts\python.exe scripts\safe_reindex.py --execute --confirm REBUILD
```

执行模式会先把三个 Milvus 集合改名为带 UTC 时间戳的备份，并备份文档 JSON、BM25 和卡片
链接数据库，再调用原有 `scripts/reindex.py`。失败时自动恢复集合和本地文件；成功时保留
`.reindex-backups/<时间戳>` 及备份集合，供人工验证后清理。原始 `scripts/reindex.py` 仍可直接
调用，但它会删除数据且没有包装层回滚保护，不建议日常使用。确认 Milvus、原始文件和 LLM
配置可用后再执行。
`page_regions` 复用已有 `metadata_json` 列，因此仅部署本次代码不需要重建 Milvus schema；
只有希望历史向量也拥有精确分页面区域时，才需要显式执行上述重建。

PDF 解析完成后，页眉页脚删除数、部分表格重叠数、OCR 尝试/采用/失败页、OCR 消息、
逐页表格后端消息以及最终 accepted/review 表格数会写入
`Document.parse_diagnostics`。全量和增量入口现有的 `doc.model_dump(mode="json")` 会把它
保存到文档 JSON；Milvus 不新增字段。旧 JSON 没有该字段时按 `None` 加载；要为历史文档
补齐诊断必须重新解析原文件。本功能只持久化既有决定，不改变 OCR 或表格路由策略。

操作员还可生成真实 PDF 解析报告，并只读检查线上 Milvus 来源字段：

```powershell
& .venv\Scripts\python.exe scripts\evaluate_pdf_parsing.py <PDF文件或目录> --output pdf-report.json
& .venv\Scripts\python.exe scripts\check_milvus_provenance.py
```

第一条支持 `--expectations <JSON>` 设置验收阈值；第二条只读查询 schema 和样本，不写数据。
以下快速检查只做编译与差异检查，也不会执行破坏性重建：

```powershell
& .venv\Scripts\python.exe -m compileall -q data-pipeline data-persistence toolset
git diff --check
```

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
