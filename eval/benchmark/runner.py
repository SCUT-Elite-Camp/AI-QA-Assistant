"""基准评估运行器

编排多配置 × 多数据集的检索评估。

两种检索后端:
1. Self-contained: 内存中 BGE embedding + cosine/BM25 (无需外部服务)
2. Full system: 通过 SearchTool 查询 Milvus + CardRetriever (需基础设施)

评估流程:
1. 加载基准数据集
2. 对每种检索配置，运行所有查询
3. 计算 NDCG@K, Recall@K, MRR@K
4. 聚合为对比结果

用法:
    python -m eval.benchmark.run --dataset MMarcoRetrieval --max-docs 500
"""

import json
import logging
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np

# 确保项目路径
project_root = Path(__file__).resolve().parent.parent.parent
for p in [
    str(project_root),
    str(project_root / "data-pipeline"),
    str(project_root / "data-persistence"),
    str(project_root / "toolset"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.benchmark.data_loader import BenchmarkDataset, load_dataset, KNOWN_DATASETS
from eval.benchmark.metrics import (
    compute_all_metrics,
    bootstrap_confidence_interval,
)

logger = logging.getLogger(__name__)


# ================================================================
# Self-contained 检索器（无需外部服务，可离线运行）
# ================================================================

class SelfContainedRetriever:
    """在内存中运行的检索器

    使用 BGE 向量 + cosine 相似度 + 可选 BM25 混合检索。
    所有数据在内存中，无需 Milvus 或其他外部服务。

    这测试的是 "embedding + 排序" 的质量，
    不是完整的系统管道（不含卡片/图谱/预压缩）。
    """

    def __init__(
        self,
        mode: str = "dense",  # dense / bm25 / hybrid
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ):
        self.mode = mode
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # 懒加载
        self._embed_fn = None
        self._corpus_chunks: list[dict] = []  # [{doc_id, chunk_id, text, embedding}]
        self._bm25_index = None
        self._bm25_tokenized_corpus = None

    def _get_embed_fn(self):
        if self._embed_fn is None:
            from pipeline.embedder import embed_texts
            self._embed_fn = embed_texts
        return self._embed_fn

    def index(self, corpus: dict[str, str]):
        """将语料库索引到内存中

        对每个文档做定长切片 → 向量化 → 存储。
        """
        import re

        embed_fn = self._get_embed_fn()
        self._corpus_chunks = []

        # 简单的句子感知切片
        def chunk_text(text: str) -> list[str]:
            sentences = re.split(r'(?<=[。！？；\n])\s*', text)
            chunks = []
            current = ""
            for sent in sentences:
                if len(current) + len(sent) > self.chunk_size and current:
                    chunks.append(current.strip())
                    current = sent
                else:
                    current += sent
            if current.strip():
                chunks.append(current.strip())
            return chunks

        all_texts = []
        chunk_meta = []
        for doc_id, text in corpus.items():
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                all_texts.append(chunk)
                chunk_meta.append({
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "chunk_id": f"{doc_id}::chunk_{i}",
                })

        logger.info(f"Embedding {len(all_texts)} chunks...")
        embeddings = embed_fn(all_texts)

        for meta, emb in zip(chunk_meta, embeddings):
            self._corpus_chunks.append({
                **meta,
                "text": all_texts[chunk_meta.index(meta)],
                "embedding": np.array(emb),
            })

        logger.info(f"Indexed {len(self._corpus_chunks)} chunks from {len(corpus)} docs")

        # BM25 索引
        if self.mode in ("bm25", "hybrid"):
            self._build_bm25()

    def _build_bm25(self):
        """构建内存 BM25 索引"""
        import jieba
        from collections import Counter
        import math

        # 分词
        self._bm25_tokenized_corpus = []
        doc_freq = Counter()
        for chunk in self._corpus_chunks:
            tokens = list(jieba.cut(chunk["text"]))
            tokens = [t.strip() for t in tokens if t.strip()]
            self._bm25_tokenized_corpus.append(tokens)
            for token in set(tokens):
                doc_freq[token] += 1

        # BM25 参数
        self._bm25_k1 = 1.5
        self._bm25_b = 0.75
        N = len(self._corpus_chunks)
        avg_dl = np.mean([len(tokens) for tokens in self._bm25_tokenized_corpus])

        # 预计算 IDF
        self._bm25_idf = {}
        for token, df in doc_freq.items():
            self._bm25_idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1)

        self._bm25_avg_dl = avg_dl
        self._bm25_N = N

    def _bm25_score(self, query_tokens: list[str], doc_idx: int) -> float:
        doc_tokens = self._bm25_tokenized_corpus[doc_idx]
        doc_len = len(doc_tokens)
        score = 0.0
        tf_counter = Counter(doc_tokens)

        for token in query_tokens:
            if token not in self._bm25_idf:
                continue
            tf = tf_counter.get(token, 0)
            idf = self._bm25_idf[token]
            numerator = tf * (self._bm25_k1 + 1)
            denominator = tf + self._bm25_k1 * (
                1 - self._bm25_b + self._bm25_b * doc_len / self._bm25_avg_dl
            )
            score += idf * numerator / denominator

        return score

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """检索

        Returns:
            [{doc_id, chunk_id, score}, ...]
        """
        import jieba
        embed_fn = self._get_embed_fn()

        if self.mode == "dense":
            query_emb = np.array(embed_fn([query])[0])
            scores = []
            for chunk in self._corpus_chunks:
                sim = float(np.dot(query_emb, chunk["embedding"]) /
                           (np.linalg.norm(query_emb) * np.linalg.norm(chunk["embedding"])))
                scores.append((sim, chunk))

            scores.sort(key=lambda x: x[0], reverse=True)
            return [
                {"doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"], "score": sim}
                for sim, chunk in scores[:top_k]
            ]

        elif self.mode == "bm25":
            query_tokens = list(jieba.cut(query))
            query_tokens = [t.strip() for t in query_tokens if t.strip()]

            scores = []
            for i, chunk in enumerate(self._corpus_chunks):
                score = self._bm25_score(query_tokens, i)
                scores.append((score, chunk))

            # 归一化
            raw = [s for s, _ in scores]
            mx = max(raw) if raw else 1
            mn = min(raw) if raw else 0
            if mx > mn:
                scores = [((s - mn) / (mx - mn), c) for s, c in scores]

            scores.sort(key=lambda x: x[0], reverse=True)
            return [
                {"doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"], "score": s}
                for s, chunk in scores[:top_k]
            ]

        elif self.mode == "hybrid":
            # Dense + BM25 via RRF
            query_emb = np.array(embed_fn([query])[0])
            query_tokens = list(jieba.cut(query))
            query_tokens = [t.strip() for t in query_tokens if t.strip()]

            results = []
            for i, chunk in enumerate(self._corpus_chunks):
                # Dense
                dense_sim = float(
                    np.dot(query_emb, chunk["embedding"]) /
                    (np.linalg.norm(query_emb) * np.linalg.norm(chunk["embedding"]))
                )
                # BM25
                bm25 = self._bm25_score(query_tokens, i) if self._bm25_tokenized_corpus else 0.0

                results.append({
                    "doc_id": chunk["doc_id"],
                    "chunk_id": chunk["chunk_id"],
                    "dense_score": dense_sim,
                    "bm25_score": bm25,
                })

            # 分别排序
            dense_ranked = sorted(enumerate(results), key=lambda x: x[1]["dense_score"], reverse=True)
            bm25_ranked = sorted(enumerate(results), key=lambda x: x[1]["bm25_score"], reverse=True)

            # RRF
            rrf_k = 60
            rrf_scores = {}
            for rank, (idx, _) in enumerate(dense_ranked, 1):
                rrf_scores[idx] = 1.0 / (rrf_k + rank)
            for rank, (idx, _) in enumerate(bm25_ranked, 1):
                rrf_scores[idx] = rrf_scores.get(idx, 0) + 1.0 / (rrf_k + rank)

            final = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
            return [
                {"doc_id": results[idx]["doc_id"], "chunk_id": results[idx]["chunk_id"], "score": s}
                for idx, s in final[:top_k]
            ]

        else:
            raise ValueError(f"Unknown mode: {self.mode}")


# ================================================================
# 评估运行器
# ================================================================

# 预定义的检索配置
RETRIEVER_CONFIGS = {
    # ── 传统基线 (self-contained, 无需外部服务) ──
    "baseline-dense": {
        "type": "self-contained",
        "mode": "dense",
        "label": "传统切片 + Dense",
    },
    "baseline-bm25": {
        "type": "self-contained",
        "mode": "bm25",
        "label": "传统切片 + BM25",
    },
    "baseline-hybrid": {
        "type": "self-contained",
        "mode": "hybrid",
        "label": "传统切片 + Hybrid RRF",
    },
    # ── A-MEM 配置 (需 Milvus + Ollama) ──
    "amem-cards": {
        "type": "system",
        "backend": "agentic",
        "mode": "vector",
        "expand_graph": False,
        "label": "A-MEM 智能卡片",
    },
    "amem-hybrid": {
        "type": "system",
        "backend": "agentic",
        "mode": "hybrid",
        "expand_graph": False,
        "label": "A-MEM 卡片+段落 双路",
    },
    "amem-full": {
        "type": "system",
        "backend": "agentic",
        "mode": "hybrid",
        "expand_graph": True,
        "label": "A-MEM 全栈 (卡片+段落+图谱)",
    },
}


class BenchmarkRunner:
    """多配置 × 多数据集 评估编排器"""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else Path(__file__).parent
        self.results: dict = {}

    def run(
        self,
        dataset_name: str = "MMarcoRetrieval",
        configs: list[str] | None = None,
        max_docs: Optional[int] = 500,
        max_queries: Optional[int] = None,
        top_k: int = 10,
        k_values: list[int] | None = None,
    ) -> dict:
        """运行完整的基准评估

        Args:
            dataset_name: 数据集名称
            configs: 要运行的配置列表，默认所有预定义配置
            max_docs: 限制语料库文档数 (None = 全部)
            max_queries: 限制查询数 (None = 全部有标注的)
            top_k: 检索返回数量
            k_values: 评估的 K 值列表

        Returns:
            完整评估结果字典
        """
        if k_values is None:
            k_values = [1, 3, 5, 10]

        if configs is None:
            configs = list(RETRIEVER_CONFIGS.keys())

        logger.info(f"{'='*60}")
        logger.info(f"Benchmark Evaluation: {dataset_name}")
        logger.info(f"Configs: {configs}")
        logger.info(f"Max docs: {max_docs}, Top-K: {top_k}")
        logger.info(f"{'='*60}")

        # 1. 加载数据集
        dataset = load_dataset(dataset_name, max_docs=max_docs)
        logger.info(f"Dataset stats: {dataset.stats}")

        # 获取有标注的查询
        annotated_queries = dataset.get_queries_with_qrels()
        if max_queries:
            annotated_queries = annotated_queries[:max_queries]

        logger.info(f"Evaluating on {len(annotated_queries)} annotated queries")

        all_results = {}

        for config_name in configs:
            cfg = RETRIEVER_CONFIGS.get(config_name)
            if cfg is None:
                logger.warning(f"Unknown config: {config_name}, skipping")
                continue

            logger.info(f"\n--- Running config: {config_name} ({cfg['label']}) ---")

            if cfg["type"] == "self-contained":
                retriever = SelfContainedRetriever(mode=cfg["mode"])
                retriever.index(dataset.corpus)

                all_results[config_name] = self._run_retrieval_eval(
                    retriever=retriever,
                    queries=annotated_queries,
                    qrels=dataset.qrels,
                    top_k=top_k,
                    k_values=k_values,
                    config_label=cfg["label"],
                )

            elif cfg["type"] == "system":
                # 需要 SearchTool + Milvus + Ollama
                result = self._run_system_eval(
                    config=cfg,
                    config_name=config_name,
                    dataset=dataset,
                    queries=annotated_queries,
                    top_k=top_k,
                    k_values=k_values,
                )
                if result:
                    all_results[config_name] = result

            else:
                logger.warning(f"Unknown config type: {cfg['type']}")

        self.results = all_results
        return all_results

    def _run_retrieval_eval(
        self,
        retriever,
        queries: list[tuple[str, str]],
        qrels: dict[str, dict[str, int]],
        top_k: int,
        k_values: list[int],
        config_label: str = "",
    ) -> dict:
        """对单个检索器运行全量查询评估"""
        per_query_metrics = []
        latencies = []

        for qid, query_text in queries:
            qrel = qrels.get(qid, {})

            start = time.perf_counter()
            results = retriever.search(query_text, top_k=top_k)
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)

            retrieved_ids = [r["doc_id"] for r in results]

            metrics = compute_all_metrics(retrieved_ids, qrel, k_values)
            metrics["query_id"] = qid
            metrics["latency_ms"] = latency_ms
            per_query_metrics.append(metrics)

        # 聚合
        aggregated = {"config": config_label, "num_queries": len(queries)}
        for k in k_values:
            for metric in [f"NDCG@{k}", f"Recall@{k}", f"Precision@{k}", f"MRR@{k}"]:
                scores = [m[metric] for m in per_query_metrics]
                mean_val = float(np.mean(scores)) if scores else 0.0
                ci_low, ci_high = bootstrap_confidence_interval(scores)
                aggregated[metric] = mean_val
                aggregated[f"{metric}_ci_low"] = ci_low
                aggregated[f"{metric}_ci_high"] = ci_high

        avg_lat = float(np.mean(latencies)) if latencies else 0.0
        aggregated["avg_latency_ms"] = avg_lat

        logger.info(f"  NDCG@10: {aggregated.get('NDCG@10', 0):.4f}  "
                     f"Recall@10: {aggregated.get('Recall@10', 0):.4f}  "
                     f"MRR@10: {aggregated.get('MRR@10', 0):.4f}  "
                     f"Latency: {avg_lat:.1f}ms")

        return {
            "summary": aggregated,
            "per_query": per_query_metrics,
        }

    def _run_system_eval(
        self,
        config: dict,
        config_name: str,
        dataset,
        queries: list[tuple[str, str]],
        top_k: int,
        k_values: list[int],
    ) -> dict | None:
        """使用 SearchTool 运行系统级评估（需 Milvus + Ollama）

        当基础设施不可用时跳过，返回 None。
        """
        try:
            from tool_layer.search_tool import SearchTool
        except ImportError:
            logger.warning(
                f"  [{config_name}] SearchTool not available, skipping A-MEM config. "
                f"Start Milvus + Ollama and ensure data is indexed."
            )
            return None

        # 检查 Milvus 连通性
        try:
            from pymilvus import connections
            connections.connect(host="localhost", port="19530", timeout=3)
            connections.disconnect("default")
        except Exception:
            logger.warning(
                f"  [{config_name}] Milvus not reachable, skipping. "
                f"Start Milvus on localhost:19530."
            )
            return None

        backend = config.get("backend", "agentic")
        mode = config.get("mode", "hybrid")

        tool = SearchTool()
        per_query_metrics = []
        latencies = []

        for qid, query_text in queries:
            qrel = dataset.qrels.get(qid, {})

            start = time.perf_counter()
            try:
                results = tool.search(
                    query=query_text,
                    top_k=top_k,
                    mode=mode,
                    backend=backend,
                )
                latency_ms = (time.perf_counter() - start) * 1000
                latencies.append(latency_ms)

                # A-MEM 结果使用 card_id/segment_id 作为 doc_id
                # 公共基准的 qrels 使用原始 doc_id，需要映射
                retrieved_ids = [
                    r.get("chunk_id", r.get("card_id", ""))
                    for r in results
                ]
                metrics = compute_all_metrics(retrieved_ids, qrel, k_values)
            except Exception as e:
                logger.error(f"  [{config_name}] Error on query {qid}: {e}")
                latencies.append(0)
                metrics = {f"NDCG@{k}": 0.0 for k in k_values}
                metrics.update({f"Recall@{k}": 0.0 for k in k_values})
                metrics.update({f"MRR@{k}": 0.0 for k in k_values})

            metrics["query_id"] = qid
            metrics["latency_ms"] = latency_ms if latencies[-1] > 0 else 0
            per_query_metrics.append(metrics)

        # 聚合
        aggregated = {"config": config["label"], "num_queries": len(queries)}
        for k in k_values:
            for metric in [f"NDCG@{k}", f"Recall@{k}", f"MRR@{k}"]:
                scores = [m[metric] for m in per_query_metrics]
                mean_val = float(np.mean(scores)) if scores else 0.0
                ci_low, ci_high = bootstrap_confidence_interval(scores)
                aggregated[metric] = mean_val
                aggregated[f"{metric}_ci_low"] = ci_low
                aggregated[f"{metric}_ci_high"] = ci_high

        avg_lat = float(np.mean(latencies)) if latencies else 0.0
        aggregated["avg_latency_ms"] = avg_lat

        logger.info(
            f"  [{config_name}] NDCG@10: {aggregated.get('NDCG@10', 0):.4f}  "
            f"Recall@10: {aggregated.get('Recall@10', 0):.4f}  "
            f"Latency: {avg_lat:.1f}ms"
        )

        return {"summary": aggregated, "per_query": per_query_metrics}


# ================================================================
# CLI
# ================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AI-QA-Assistant 公开基准评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
可用数据集:
{chr(10).join(f'  {k}: {v["description"]}' for k, v in KNOWN_DATASETS.items())}

可用检索配置:
{chr(10).join(f'  {k}: {v["label"]}' for k, v in RETRIEVER_CONFIGS.items())}

示例:
  # 小规模快速测试
  python -m eval.benchmark.run --dataset MMarcoRetrieval --max-docs 100 --max-queries 20

  # 全量评估
  python -m eval.benchmark.run --dataset MMarcoRetrieval --max-docs 1000
        """,
    )
    parser.add_argument("--dataset", default="builtin-zh",
                       help="数据集名称")
    parser.add_argument("--configs", default="baseline-dense,baseline-bm25,baseline-hybrid",
                       help="检索配置，逗号分隔")
    parser.add_argument("--max-docs", type=int, default=500,
                       help="限制语料库文档数")
    parser.add_argument("--max-queries", type=int, default=None,
                       help="限制查询数")
    parser.add_argument("--top-k", type=int, default=10,
                       help="检索返回数量")
    parser.add_argument("--output", default="benchmark_results.json",
                       help="结果输出文件")

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    configs = [c.strip() for c in args.configs.split(",")]

    runner = BenchmarkRunner()
    results = runner.run(
        dataset_name=args.dataset,
        configs=configs,
        max_docs=args.max_docs,
        max_queries=args.max_queries,
        top_k=args.top_k,
    )

    # 保存结果
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(__file__).parent / output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 简化的输出（只保存摘要 + 可选的完整结果）
    summary = {
        "dataset": args.dataset,
        "settings": {
            "max_docs": args.max_docs,
            "max_queries": args.max_queries,
            "top_k": args.top_k,
        },
        "results": {},
    }

    for config_name, config_results in results.items():
        summary["results"][config_name] = config_results["summary"]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to: {output_path}")

    # 打印摘要
    from eval.benchmark.report import print_comparison_table
    print_comparison_table(summary)


if __name__ == "__main__":
    main()
