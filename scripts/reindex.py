"""重建索引 — 用中文 embedding 模型重建所有数据"""
import sys, os, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "data-persistence"))
sys.path.insert(0, str(PROJECT_ROOT / "toolset"))

# 1. 删除旧集合
from pymilvus import connections, utility
connections.connect(host='localhost', port='19530')

for name in ['doc_chunks', 'knowledge_cards', 'semantic_segments']:
    if utility.has_collection(name):
        utility.drop_collection(name)
        print(f'[OK] Dropped: {name}')
    else:
        print(f'[--] Not found: {name}')

# 2. 删除旧 BM25 索引
bm25_path = PROJECT_ROOT / "data-persistence" / "data" / "bm25_index.pkl"
if bm25_path.exists():
    bm25_path.unlink()
    print(f'[OK] Deleted BM25 index')

# 3. 删除旧卡片链接数据库
card_db = PROJECT_ROOT / "data-persistence" / "data" / "card_links.db"
if card_db.exists():
    card_db.unlink()
    print(f'[OK] Deleted card links DB')

# 4. 重建文档分块索引
print('\n[..] Re-indexing document chunks...')
from pipeline.auto_process import auto_process_raws
auto_process_raws()

# 5. 验证
collections = utility.list_collections()
print(f'\n[OK] Milvus collections: {collections}')
for name in collections:
    from pymilvus import Collection
    c = Collection(name)
    c.load()
    print(f'  {name}: {c.num_entities} entities')

# 6. 运行知识卡片构建管道
print('\n[..] Building knowledge cards...')
from pipeline.embedder import embed_texts
from segmenter.similarity_segmenter import SimilaritySegmenter
from knowledge_cards.schemas import KnowledgeCard
from knowledge_cards.card_builder import CardConstructor
from knowledge_cards.card_linker import CardLinker
from knowledge_cards.card_evolver import CardEvolver
from knowledge_cards.stm_buffer import STMBufferManager
from knowledge_cards.card_store import CardStore
from parsers.registry import parse_file
from pipeline.chunker import chunk_text, chunk_from_blocks

RAWS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "raws"
DOCS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "documents"

# 初始化组件
segmenter = SimilaritySegmenter(similarity_threshold=0.65)
card_constructor = CardConstructor(llm_model="llama3.1")
card_store = CardStore()
asyncio_imported = False
try:
    import asyncio
    asyncio_imported = True
except Exception:
    pass

# 处理每个文档
doc_files = sorted(DOCS_DIR.glob("*.json"))
total_cards = 0

for doc_file in doc_files:
    try:
        with open(doc_file, 'r', encoding='utf-8') as f:
            doc_data = json.load(f)
    except Exception as e:
        print(f'  [SKIP] {doc_file.name}: {e}')
        continue

    doc_id = doc_data.get('doc_id', doc_file.stem)
    chunks = doc_data.get('chunks', [])
    if not chunks:
        print(f'  [SKIP] {doc_file.name}: no chunks')
        continue

    # 对每个 chunk 做语义分段 + 卡片提取
    all_cards = []
    for chunk in chunks:
        text = chunk.get('text', chunk.get('chunk_text', ''))
        if len(text) < 50:
            continue

        # 语义分段
        segments = segmenter.segment(text, doc_id=doc_id)
        if not segments:
            continue

        # STM 缓冲区管理 + 批量卡片构建
        stm = STMBufferManager(
            token_threshold=2000,
            card_constructor=card_constructor,
        )
        for seg in segments:
            cards = stm.add(seg)
            if cards:
                all_cards.extend(cards)

        # flush 剩余
        remaining = stm.flush_all()
        all_cards.extend(remaining)

    if all_cards:
        # 为卡片生成 embedding
        card_texts = [c.combined_text() for c in all_cards]
        embeddings = embed_texts(card_texts)
        for card, emb in zip(all_cards, embeddings):
            card.embedding = emb

        # 卡片链接
        linker = CardLinker(card_store=card_store, llm_model="llama3.1")
        linked_cards, links = linker.link_batch_simple(all_cards)
        if links:
            card_store.add_links_batch(links)

        # 卡片演化
        evolver = CardEvolver(llm_model="llama3.1")
        existing_map = {}
        existing_embs = {}
        # (简化: 新卡片之间互相演化)
        final_cards = evolver.evolve(all_cards, existing_embs, existing_map)

        # 入库
        if asyncio_imported:
            asyncio.run(card_store.insert_cards(final_cards))
        total_cards += len(final_cards)
        print(f'  [{doc_id}] {len(final_cards)} cards')

print(f'\n[OK] Total cards: {total_cards}')

# 最终验证
print('\n[Final] Collections:')
for name in utility.list_collections():
    from pymilvus import Collection
    c = Collection(name)
    c.load()
    print(f'  {name}: {c.num_entities} entities')

print('\n[DONE]')
