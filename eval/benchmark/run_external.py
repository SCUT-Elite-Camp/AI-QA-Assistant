"""外部基准数据集适配器

通过 mteb 库加载公共基准数据集，转换为标准 BenchmarkDataset 格式，
然后运行检索评估。

用法:
    python -m eval.benchmark.run_external --task MMarcoRetrieval --max-docs 1000
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

project_root = Path(__file__).resolve().parent.parent.parent
for p in [
    str(project_root),
    str(project_root / "data-pipeline"),
    str(project_root / "data-persistence"),
    str(project_root / "toolset"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.benchmark.data_loader import BenchmarkDataset
from eval.benchmark.metrics import (
    compute_all_metrics,
    ndcg_at_k,
    recall_at_k,
    mrr_at_k,
    bootstrap_confidence_interval,
)
from eval.benchmark.runner import SelfContainedRetriever, RETRIEVER_CONFIGS

logger = logging.getLogger(__name__)

# 可用的中文检索任务
AVAILABLE_TASKS = ["MMarcoRetrieval", "T2Retrieval", "DuRetrieval", "CmedqaRetrieval"]


def load_mteb_dataset(
    task_name: str,
    max_docs: Optional[int] = None,
    max_queries: Optional[int] = None,
) -> BenchmarkDataset:
    """通过 mteb 加载公共基准数据集

    Args:
        task_name: 任务名 (MMarcoRetrieval, T2Retrieval, DuRetrieval, CmedqaRetrieval)
        max_docs: 限制语料库文档数
        max_queries: 限制查询数

    Returns:
        BenchmarkDataset 实例
    """
    import mteb

    logger.info(f"Loading {task_name} via mteb...")
    task = mteb.get_task(task_name)

    # mteb 任务加载时会自动下载数据集到本地缓存
    task.load_data()

    ds = BenchmarkDataset(task_name)

    # MTEB 任务数据结构: task.dataset['default'][split]
    # split 通常为 'dev' 或 'test'
    task_data = getattr(task, "dataset", {})
    if not task_data:
        logger.warning("No dataset found in task")
        return ds

    # 获取第一个可用的 subset 和 split
    subset = list(task_data.keys())[0] if task_data else "default"
    splits = task_data.get(subset, {})
    split = list(splits.keys())[0] if splits else "dev"
    data = splits.get(split, {})

    # 提取 corpus (HuggingFace Dataset)
    corpus_ds = data.get("corpus", data.get("docs", None))
    if corpus_ds is not None:
        logger.info(f"Extracting corpus: {len(corpus_ds)} entries")
        for i, row in enumerate(corpus_ds):
            if max_docs and i >= max_docs:
                break
            doc_id = str(row.get("_id", row.get("id", i)))
            title = str(row.get("title", ""))
            text = str(row.get("text", ""))
            full_text = (title + " " + text).strip() if title else text
            if full_text:
                ds.corpus[doc_id] = full_text
    else:
        logger.warning("No corpus found in task")

    # 提取 qrels FIRST（dict: query_id → {doc_id: score}）
    qrels = data.get("relevant_docs", data.get("qrels", {}))
    ds_qrels = {}
    if qrels:
        logger.info(f"Extracting qrels: {len(qrels)} query-doc pairs")
        for qid, doc_rels in qrels.items():
            qid = str(qid)
            if isinstance(doc_rels, dict):
                ds_qrels[qid] = {str(did): int(score) for did, score in doc_rels.items()}
            elif isinstance(doc_rels, (list, set)):
                ds_qrels[qid] = {str(did): 1 for did in doc_rels}

    # 提取 queries — 只加载有 qrels 标注的
    queries_ds = data.get("queries", data.get("questions", None))
    if queries_ds is not None:
        logger.info(f"Extracting queries: {len(queries_ds)} entries")
        qrel_ids = set(ds_qrels.keys())
        loaded = 0
        for row in queries_ds:
            qid = str(row.get("_id", row.get("id", "")))
            if qid not in qrel_ids:
                continue  # 只加载有标注的查询
            qtext = str(row.get("text", row.get("query", "")))
            if qtext:
                ds.queries[qid] = qtext
                ds.qrels[qid] = ds_qrels[qid]
                loaded += 1
                if max_queries and loaded >= max_queries:
                    break
        logger.info(f"Matched {loaded} queries with qrels")

    ds._loaded = True
    logger.info(f"Loaded: {len(ds.corpus)} docs, {len(ds.queries)} queries, {len(ds.qrels)} annotated")
    return ds


def run_benchmark(
    task_name: str = "MMarcoRetrieval",
    configs: list[str] | None = None,
    max_docs: Optional[int] = 500,
    max_queries: Optional[int] = 100,
    top_k: int = 10,
    k_values: list[int] | None = None,
) -> dict:
    """运行外部基准评估

    Returns:
        {config_name: {summary: {}, per_query: []}} 结果字典
    """
    if k_values is None:
        k_values = [1, 3, 5, 10]
    if configs is None:
        configs = ["baseline-dense", "baseline-bm25", "baseline-hybrid"]

    logger.info(f"{'='*60}")
    logger.info(f"External Benchmark: {task_name}")
    logger.info(f"Configs: {configs}")
    logger.info(f"Max docs: {max_docs}, Max queries: {max_queries}")
    logger.info(f"{'='*60}")

    # 1. 加载数据集
    dataset = load_mteb_dataset(task_name, max_docs=max_docs, max_queries=max_queries)
    logger.info(f"Stats: {dataset.stats}")

    annotated = dataset.get_queries_with_qrels()
    logger.info(f"Evaluating on {len(annotated)} queries")

    all_results = {}

    for config_name in configs:
        cfg = RETRIEVER_CONFIGS.get(config_name)
        if cfg is None:
            logger.warning(f"Unknown config: {config_name}")
            continue

        logger.info(f"\n--- {config_name}: {cfg['label']} ---")

        if cfg["type"] == "self-contained":
            retriever = SelfContainedRetriever(mode=cfg["mode"])
            retriever.index(dataset.corpus)

            config_result = _run_retrieval_eval(
                retriever=retriever,
                queries=annotated,
                qrels=dataset.qrels,
                top_k=top_k,
                k_values=k_values,
                config_label=cfg["label"],
            )
            all_results[config_name] = config_result
        else:
            logger.warning(f"Config type '{cfg['type']}' not supported")

    return all_results


def _run_retrieval_eval(
    retriever,
    queries: list[tuple[str, str]],
    qrels: dict[str, dict[str, int]],
    top_k: int,
    k_values: list[int],
    config_label: str,
) -> dict:
    """运行单配置的全量查询评估"""
    per_query = []
    latencies = []

    for qid, query_text in queries:
        qrel = qrels.get(qid, {})

        start = time.perf_counter()
        results = retriever.search(query_text, top_k=top_k)
        lat_ms = (time.perf_counter() - start) * 1000
        latencies.append(lat_ms)

        retrieved_ids = [r["doc_id"] for r in results]
        metrics = compute_all_metrics(retrieved_ids, qrel, k_values)
        metrics["query_id"] = qid
        metrics["latency_ms"] = lat_ms
        per_query.append(metrics)

    # 聚合
    agg = {"config": config_label, "num_queries": len(queries)}
    for k in k_values:
        for metric in [f"NDCG@{k}", f"Recall@{k}", f"MRR@{k}"]:
            scores = [m[metric] for m in per_query]
            mean_val = float(np.mean(scores)) if scores else 0.0
            ci_low, ci_high = bootstrap_confidence_interval(scores)
            agg[metric] = mean_val
            agg[f"{metric}_ci_low"] = ci_low
            agg[f"{metric}_ci_high"] = ci_high

    agg["avg_latency_ms"] = float(np.mean(latencies)) if latencies else 0.0

    logger.info(
        f"  NDCG@10: {agg.get('NDCG@10', 0):.4f}  "
        f"Recall@10: {agg.get('Recall@10', 0):.4f}  "
        f"MRR@10: {agg.get('MRR@10', 0):.4f}  "
        f"Latency: {agg['avg_latency_ms']:.1f}ms"
    )

    return {"summary": agg, "per_query": per_query}


# ================================================================
# CLI
# ================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AI-QA-Assistant 外部检索基准评估（via MTEB）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
可用任务:
  MMarcoRetrieval  - 中文 MS MARCO 段落检索 (~7,437 queries, 8.8M docs)
  T2Retrieval       - T2Ranking 中文段落检索 (~24,832 queries)
  DuRetrieval       - 百度 DuReader 中文检索
  CmedqaRetrieval   - 中文医疗检索

示例:
  # 小规模快速测试
  python -m eval.benchmark.run_external --task MMarcoRetrieval --max-docs 100 --max-queries 20

  # 中等规模
  python -m eval.benchmark.run_external --task MMarcoRetrieval --max-docs 1000 --max-queries 100
        """,
    )
    parser.add_argument("--task", default="MMarcoRetrieval",
                       help="MTEB 任务名")
    parser.add_argument("--configs", default="baseline-dense,baseline-bm25,baseline-hybrid",
                       help="检索配置")
    parser.add_argument("--max-docs", type=int, default=1000,
                       help="限制语料库文档数")
    parser.add_argument("--max-queries", type=int, default=200,
                       help="限制查询数")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", default="external_benchmark_results.json")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    configs = [c.strip() for c in args.configs.split(",")]

    results = run_benchmark(
        task_name=args.task,
        configs=configs,
        max_docs=args.max_docs,
        max_queries=args.max_queries,
        top_k=args.top_k,
    )

    # 保存
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(__file__).parent / output_path

    summary_out = {
        "task": args.task,
        "settings": {
            "max_docs": args.max_docs,
            "max_queries": args.max_queries,
            "top_k": args.top_k,
        },
        "results": {},
    }
    for cfg_name, cfg_data in results.items():
        summary_out["results"][cfg_name] = cfg_data["summary"]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary_out, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to: {output_path}")

    from eval.benchmark.report import print_comparison_table
    print_comparison_table(summary_out)


if __name__ == "__main__":
    main()
