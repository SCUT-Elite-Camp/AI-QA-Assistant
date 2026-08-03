
---
新管线流程

  原始 PDF/DOCX
    │
    ▼
  解析 (PyMuPDF / python-docx)          ← 不变
    │
    ▼
  P₀: 预压缩 (EntropyCompressor)       ← 过滤低信息量内容
    │
    ▼
  B₂: 语义分割 (SimilaritySegmenter)    ← 替换旧 chunk_text/chunk_from_blocks
    │  • 句子级 embedding
    │  • 相邻余弦相似度 → 检测语义边界
    │  • topic 聚类 → 同一话题的段共享 topic_id
    │
    ├──→ doc_chunks (Milvus)           ← 兼容标准向量检索
    ├──→ semantic_segments (Milvus)    ← 供 CardRetriever 双路检索
    └──→ BM25 倒排索引                  ← 关键词检索
    │
    ▼
  P_s1: STM Buffer → CardConstructor (LLM)
    │  • 同 topic 段落聚合到独立 buffer
    │  • buffer 满后批量调用 LLM 提取知识卡片
    │  • 跨段事实自动合并（source_segments 标记）
    │
    ▼
  P_s2: CardLinker (向量 top-k + LLM judge)
    │  • 为新卡片建立与已有卡片的语义链接
    │  • 双向关系存入 SQLite
    │
    ▼
  P_s3: CardEvolver (LLM)
    │  • 新卡片与已有卡片比较 (cosine 0.72~0.85)
    │  • EVOLVE → 更新旧卡片 | CONFLICT → 标记矛盾
    │  • EXPAND → 合并补充 | NEW → 保持独立
    │
    ▼
  knowledge_cards (Milvus) + card_links (SQLite)

  旧分块 vs 新语义分割

  ┌──────────────┬────────────────────────┬───────────────────────────────────────┐
  │   对比维度   │     旧（固定分块）     │            新（语义分割）             │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ 切割方式     │ 500字符滑动窗口        │ 句子相似度边界检测                    │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ 边界质量     │ 随意截断句子           │ 语义边界对齐                          │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ 表格处理     │ 块感知不切割表格       │ 整个表格作为一个语义单元              │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ 话题追踪     │ 无                     │ topic_id 聚类同主题段落               │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ Token 利用率 │ 低（大量无关内容混入） │ 高（语义自包含）                      │
  ├──────────────┼────────────────────────┼───────────────────────────────────────┤
  │ LLM 联动     │ 无                     │ STM buffer → CardConstructor 批量提取 │
  └──────────────┴────────────────────────┴───────────────────────────────────────┘
---

## 2. 嵌入模型升级

### 变更

```python
# data-pipeline/pipeline/embedder.py
# BEFORE
_LOCAL_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384维, 英文
# AFTER
_LOCAL_MODEL_NAME = "BAAI/bge-large-zh-v1.5"  # 1024维, 中文
```

| 对比维度 | 旧模型 | 新模型 |
|----------|--------|--------|
| 参数量 | 24M (small) | 326M (large) |
| 向量维度 | 384 | 1024 |
| 训练语料 | 英文为主 | 中文为主 + 多语言 |
| MTEB-zh 评分 | ~55 | ~67 |

### 注意事项
- **需重建向量库**：维度变化，旧 Milvus 集合 `doc_chunks` 需删除后重新入库
- `card_store.py` 的 `DEFAULT_DIM` 同步更新为 1024
---

## 3. Cross-Encoder 重排序

### 架构位置

```
检索 → RRF融合 → Top-20候选池 → Cross-Encoder精排 → Top-K → 上下文
```

### 实现: `toolset/retrieval/reranker.py`

```python
class Reranker:
    """默认 BAAI/bge-reranker-v2-m3, 通过 RERANK_ENABLED=true 开启"""
    
    def __init__(self, candidate_pool_size=20, fusion_weight=0.7):
        ...
    
    def rerank(self, query, chunks, top_k=5):
        # 1. 取前 candidate_pool_size 个候选
        # 2. 构建 (query, chunk_text) 对送入 Cross-Encoder
        # 3. 预测相关性分数 → 归一化
        # 4. fusion: final_score = (1-w)*original + w*rerank
        # 5. 按融合分数降序返回 top_k
```

### 关键设计

| 特性 | 决策 |
|------|------|
| 默认状态 | 关闭 (RERANK_ENABLED=false)，避免额外延迟 |
| 模型加载 | 懒加载 + LRU 缓存，首次 ~1s，后续 0ms |
| 故障模式 | 模型不可用 → 跳过精排，输出原始结果 |
| 候选池大小 | 20（可配），平衡精度与延迟 |
| 融合权重 | 默认 0.7 rerank / 0.3 原始（可调） |

### 延迟分析

| 场景 | Reranker 延迟 | 说明 |
|------|-------------|------|
| 首次调用 | ~500ms | 模型加载（含下载，仅首次） |
| 后续调用 | ~50-100ms | 模型已缓存到内存 |
| 失败降级 | +0ms | 自动跳过，返回原始结果 |

---

## 4. 检索内容去重

### 算法: n-gram Jaccard 相似度 (`search_tool._deduplicate`)

```
输入: 按 score 降序的候选列表
输出: 去重后的列表

for each candidate (按 score 从高到低):
    提取 chunk_text 的 3-gram 字符集合
    for each 已保留的结果:
        if 同文档 && |chunk_index差| ≤ 1:  跳过 (相邻chunk保护)
        jaccard = |A∩B| / |A∪B|
        if jaccard ≥ 0.75:  标记重复，丢弃
    未标记 → 加入保留列表
```

**设计要点**：同一文档相邻 chunk（chunk_index 差 ≤ 1）不触发去重——它们内容不同但主题相关，应保留。

---

## 5. Token 预算管理

### 估算算法 (`toolset/retrieval/token_utils.py`)

```python
def estimate_tokens(text: str) -> int:
    cjk = len(_CJK_RE.findall(text))         # 中日韩字符
    non_cjk = len(text) - cjk                 # ASCII/其他
    return max(1, int(cjk / 1.5 + non_cjk / 4.0))
```

| 文本类型 | 估算公式 | 示例 |
|----------|---------|------|
| 纯中文 | chars / 1.5 | 1500 字 ≈ 1000 tokens |
| 纯英文 | chars / 4.0 | 4000 字符 ≈ 1000 tokens |
| 混合 | 加权平均 | 自动按 CJK 比例分配 |

### CJK 覆盖范围

```python
_CJK_RE = re.compile(
    r"[⺀-⿟　-〿㐀-䶿"
    r"一-鿿豈-﫿︰-﹏"
    r"\U00020000-\U0002A6DF\U0002F800-\U0002FA1F]"
)
# 覆盖: 部首补充/康熙部首/CJK符号/CJK统一汉字/兼容汉字/兼容形式/扩展A-B
```

### 截断策略

`truncate_by_tokens()`: 超出预算时按比例截断，在 `\n\n` → `\n` → `。` → `；` → `，` 优先级寻找最近的句子边界。

### 配置

| 环境变量 | 默认值 |
|----------|--------|
| `TOKEN_BUDGET_ENABLED` | `true` |
| `MAX_CONTEXT_TOKENS` | `3000` |

---

## 6. BM25 增量更新

### 问题

原有 `auto_process.py` 每次入库都调用 `bm25.build_from_documents()` 全量重建，需重新读取所有 JSON 文件并 jieba 分词。

### 改进

```python
# bm25_index.py 新增方法

build_from_documents(doc_ids=["doc1", "doc2"])  # 指定doc_id列表 → 增量模式
add_document(doc_id)           # 单个增量添加
add_documents([id1, id2])      # 批量增量添加
remove_documents([id1, id2])   # 移除指定文档的所有分块
```

### 增量流程

```
auto_process.py:
  1. 检测已有 bm25_index.pkl → 加载
  2. build_from_documents(doc_ids=本次处理的doc_id列表)
     → remove_documents(doc_ids) 清旧条目
     → 追加新分块
     → jieba 重分词 + 重建 BM25Okapi
  3. save() 持久化
```

### 复杂度对比

| 操作 | 全量模式 | 增量模式 |
|------|---------|---------|
| 读取 JSON | O(N) 所有文档 | O(K) 仅变更文档 |
| 分词 | O(N×L) | O(K×L + M) K≪N |
| 典型耗时 (100 docs) | ~5s | ~0.5s |

---
## 10. 数据质量校验

### 新增: `pipeline/quality.py`

```
QualityReport {
    level:       OK | WARN | REJECT
    warnings:    ["3个空分块"]
    errors:      ["有效内容比例过低 (3.2%)"]
    
    total_chars, meaningful_chars, garbage_chars
    meaningful_ratio, empty_chunk_count
}
```

### 检测规则

| 规则 | 阈值 | 动作 |
|------|------|------|
| 文档内容过短 | < 20 字符 | REJECT |
| 无有效内容 | meaningful_chars = 0 | REJECT |
| 有效内容比例过低 | < 5% | WARN |
| 大量乱码字符 | > 30% 异常字符 | REJECT |
| 少量异常字符 | > 10 个 | WARN |
| 所有分块为空 | empty_chunk_count = total | REJECT |
| 无分块 | total_chunks = 0 | REJECT |

### 集成位置

`process.py` 和 `auto_process.py` 中，在分块后进行质量检查：

```python
quality_report = check_document_quality(doc.doc_id, doc.title, chunks, doc.content)
if should_skip(quality_report):
    print(f"质量不达标，跳过入库")  # 不写入 Milvus + JSON + BM25
    continue
```

---
