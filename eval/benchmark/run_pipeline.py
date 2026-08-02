"""真正测试项目智能管道的基准

把 MMarcoRetrieval 语料喂进真实管道:
  SimilaritySegmenter → EntropyCompressor → CardConstructor → CardLinker
  → CardRetriever(hybrid+graph) 检索 → 对比 baseline(定长切片+dense)

用法:
  python -m eval.benchmark.run_pipeline --max-docs 100 --max-queries 50
"""

import json, logging, sys, time, asyncio
from pathlib import Path
from typing import Optional
import numpy as np

project_root = Path(__file__).resolve().parent.parent.parent
for p in [str(project_root), str(project_root/"data-pipeline"),
          str(project_root/"data-persistence"), str(project_root/"toolset")]:
    if p not in sys.path: sys.path.insert(0, p)

from eval.benchmark.data_loader import load_dataset
from eval.benchmark.metrics import compute_all_metrics, bootstrap_confidence_interval

logger = logging.getLogger(__name__)


class PipelineRetriever:
    """使用项目真实管道: 语义分段 + 卡片 + 图谱"""

    def __init__(self, use_cards: bool = True, use_graph: bool = True):
        self.use_cards = use_cards
        self.use_graph = use_graph
        self._retriever = None

    def index(self, corpus: dict[str, str]):
        """通过真实管道处理语料并入库"""
        from pymilvus import connections, utility
        connections.connect(host='localhost', port='19530')

        from segmenter.similarity_segmenter import SimilaritySegmenter
        from knowledge_cards.card_builder import CardConstructor
        from knowledge_cards.stm_buffer import STMBufferManager
        from knowledge_cards.card_store import CardStore
        from knowledge_cards.card_retriever import CardRetriever
        from pipeline.embedder import embed_texts

        segmenter = SimilaritySegmenter(similarity_threshold=0.65)
        card_store = CardStore()

        # 初始化集合
        async def _init():
            await card_store.init()
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                ex.submit(asyncio.run, _init()).result(timeout=30)
        except RuntimeError:
            asyncio.run(_init())

        if self.use_cards:
            card_constructor = CardConstructor(llm_model="llama3.1")

        total_segments = 0
        total_cards = 0

        logger.info(f"Processing {len(corpus)} docs through pipeline...")
        for i, (doc_id, text) in enumerate(corpus.items()):
            if len(text) < 50:
                continue

            # 1. 语义分段
            segments = segmenter.segment(text, doc_id=doc_id)
            if not segments:
                continue
            total_segments += len(segments)

            # 2. 段落入库
            seg_texts = [s.text for s in segments]
            seg_embs = embed_texts(seg_texts)
            async def _insert_segs():
                await card_store.insert_segments(segments, seg_embs)
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as ex:
                    ex.submit(asyncio.run, _insert_segs()).result(timeout=60)
            except RuntimeError:
                asyncio.run(_insert_segs())

            # 3. 知识卡片提取
            if self.use_cards:
                stm = STMBufferManager(token_threshold=2000, card_constructor=card_constructor)
                all_cards = []
                for seg in segments:
                    cards = stm.add(seg)
                    if cards:
                        all_cards.extend(cards)
                all_cards.extend(stm.flush_all())

                if all_cards:
                    card_texts = [c.combined_text() for c in all_cards]
                    card_embs = embed_texts(card_texts)
                    for c, e in zip(all_cards, card_embs):
                        c.embedding = e
                    async def _insert_cards():
                        await card_store.insert_cards(all_cards)
                    try:
                        loop = asyncio.get_running_loop()
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as ex:
                            ex.submit(asyncio.run, _insert_cards()).result(timeout=60)
                    except RuntimeError:
                        asyncio.run(_insert_cards())
                    total_cards += len(all_cards)

            if (i+1) % 20 == 0:
                logger.info(f"  ... {i+1}/{len(corpus)} docs, {total_segments} segs, {total_cards} cards")

        logger.info(f"Pipeline done: {total_segments} segments, {total_cards} cards")

        # 4. 创建检索器
        self._retriever = CardRetriever(
            card_store=card_store,
            embedding_fn=embed_texts,
        )

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        if self._retriever is None:
            return []

        async def _search():
            return await self._retriever.search(
                query=query, top_k=top_k,
                search_cards=self.use_cards,
                search_segments=True,
                expand_graph=self.use_graph,
            )

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                results = ex.submit(asyncio.run, _search()).result(timeout=30)
        except RuntimeError:
            results = asyncio.run(_search())

        return [
            {"doc_id": r.id, "chunk_id": r.card_id or r.segment_id, "score": r.score}
            for r in results
        ]


class BaselineRetriever:
    """对照: 定长切片 + dense (跟 SelfContainedRetriever 相同逻辑)"""

    def __init__(self):
        self._chunks = []

    def index(self, corpus: dict[str, str]):
        import re
        from pipeline.embedder import embed_texts

        all_texts, all_doc_ids = [], []
        for doc_id, text in corpus.items():
            for sent in re.split(r'(?<=[。！？；\n])\s*', text):
                sent = sent.strip()
                if len(sent) > 30:
                    all_texts.append(sent)
                    all_doc_ids.append(doc_id)

        logger.info(f"Embedding {len(all_texts)} sentences...")
        embs = embed_texts(all_texts)

        for doc_id, text, emb in zip(all_doc_ids, all_texts, embs):
            self._chunks.append({"doc_id": doc_id, "text": text, "emb": np.array(emb)})

        logger.info(f"Baseline: {len(self._chunks)} chunks")

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        from pipeline.embedder import embed_texts
        q_emb = np.array(embed_texts([query])[0])
        scores = []
        for c in self._chunks:
            sim = float(np.dot(q_emb, c["emb"]) /
                       (np.linalg.norm(q_emb) * np.linalg.norm(c["emb"])))
            scores.append((sim, c["doc_id"]))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [{"doc_id": d, "score": s} for s, d in scores[:top_k]]


def run():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-docs", type=int, default=100)
    p.add_argument("--max-queries", type=int, default=50)
    p.add_argument("--skip-cards", action="store_true", help="跳过卡片，只测语义分段")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 加载数据集
    ds = load_dataset("builtin-zh", max_docs=50, num_queries=args.max_queries)
    queries = ds.get_queries_with_qrels()
    logger.info(f"Dataset: {ds.stats}, {len(queries)} queries")

    k_values = [1, 3, 5, 10]

    # === 对照: 定长切片 ===
    logger.info("\n=== Baseline (定长切片 + Dense) ===")
    base = BaselineRetriever()
    base.index(ds.corpus)
    base_res = _eval(base, queries, ds.qrels, k_values, 10)

    # === 语义分段 (无卡片) ===
    logger.info("\n=== Smart Segment (语义分段, 无卡片) ===")
    seg = PipelineRetriever(use_cards=False, use_graph=False)
    seg.index(ds.corpus)
    seg_res = _eval(seg, queries, ds.qrels, k_values, 10)

    # === 语义分段 + 卡片 ===
    results = {"baseline": base_res, "smart-segments": seg_res}

    if not args.skip_cards:
        logger.info("\n=== Pipeline Full (语义分段 + 卡片 + 图谱) ===")
        full = PipelineRetriever(use_cards=True, use_graph=True)
        full.index(ds.corpus)
        full_res = _eval(full, queries, ds.qrels, k_values, 10)
        results["pipeline-full"] = full_res

    # 打印对比
    print("\n" + "="*80)
    print(f"  PIPELINE BENCHMARK ({len(ds.corpus)} docs, {len(queries)} queries)")
    print("="*80)
    header = f"{'Metric':<18}"
    for name in results: header += f" {name:>20}"
    print(header)
    print("-"*80)

    for m in ["NDCG@1","NDCG@5","NDCG@10","Recall@10","MRR@10"]:
        row = f"  {m:<16}"
        best_val, best_name = -1, ""
        for name, r in results.items():
            v = r["summary"].get(m, 0)
            row += f" {v:>19.4f}"
            if v > best_val: best_val, best_name = v, name
        row += f"  <- {best_name}"
        print(row)

    print("="*80)
    for name, r in results.items():
        print(f"  {name}: latency={r['summary'].get('avg_latency_ms',0):.0f}ms")
    print("="*80)


def _eval(retriever, queries, qrels, k_values, top_k):
    per_query = []; lats = []
    for qid, qtext in queries:
        start = time.perf_counter()
        results = retriever.search(qtext, top_k=top_k)
        lats.append((time.perf_counter()-start)*1000)
        ids = [r["doc_id"] for r in results]
        m = compute_all_metrics(ids, qrels.get(qid,{}), k_values)
        m["query_id"] = qid
        per_query.append(m)

    agg = {"num_queries": len(queries)}
    for k in k_values:
        for metric in [f"NDCG@{k}", f"Recall@{k}", f"MRR@{k}"]:
            scores = [m[metric] for m in per_query]
            agg[metric] = float(np.mean(scores)) if scores else 0.0
    agg["avg_latency_ms"] = float(np.mean(lats)) if lats else 0.0

    logger.info(f"  NDCG@10={agg.get('NDCG@10',0):.4f}  Recall@10={agg.get('Recall@10',0):.4f}  lat={agg['avg_latency_ms']:.0f}ms")
    return {"summary": agg, "per_query": per_query}


if __name__ == "__main__":
    run()
