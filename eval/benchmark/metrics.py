"""检索评估指标（扩展）

在 eval/metrics.py 已有指标基础上，增加:
- NDCG@K (Normalized Discounted Cumulative Gain)
- Recall@K
- Precision@K

所有指标与 BEIR/MTEB 的评估协议保持一致。
"""

import math
import numpy as np


def dcg_at_k(relevance_scores: list[float], k: int) -> float:
    """Discounted Cumulative Gain @ K

    DCG@k = sum_{i=1}^{k} (2^rel_i - 1) / log2(i + 1)

    Args:
        relevance_scores: 按检索排名排列的相关性分数
        k: 截断位置
    """
    dcg = 0.0
    for i, rel in enumerate(relevance_scores[:k], start=1):
        dcg += (2 ** rel - 1) / math.log2(i + 1)
    return dcg


def ndcg_at_k(
    retrieved_doc_ids: list[str],
    qrels: dict[str, int],
    k: int,
) -> float:
    """Normalized DCG @ K

    NDCG@k = DCG@k / IDCG@k

    Args:
        retrieved_doc_ids: 检索返回的文档 ID 列表（按排名）
        qrels: {doc_id: relevance_score} 标准答案
        k: 截断位置

    Returns:
        NDCG@K 值 (0.0 ~ 1.0)
    """
    # 获取检索结果的相关性分数
    retrieved_rels = []
    for doc_id in retrieved_doc_ids[:k]:
        retrieved_rels.append(float(qrels.get(doc_id, 0)))

    dcg = dcg_at_k(retrieved_rels, k)

    # 计算 IDCG (理想排序)
    ideal_rels = sorted(qrels.values(), reverse=True)
    idcg = dcg_at_k(ideal_rels, k)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def precision_at_k(
    retrieved_doc_ids: list[str],
    qrels: dict[str, int],
    k: int,
) -> float:
    """Precision @ K

    Args:
        retrieved_doc_ids: 检索返回的文档 ID 列表
        qrels: {doc_id: relevance_score} (score > 0 视为相关)
        k: 截断位置
    """
    if k <= 0:
        return 0.0

    relevant = sum(
        1 for doc_id in retrieved_doc_ids[:k]
        if qrels.get(doc_id, 0) > 0
    )
    return relevant / k


def recall_at_k(
    retrieved_doc_ids: list[str],
    qrels: dict[str, int],
    k: int,
) -> float:
    """Recall @ K

    Args:
        retrieved_doc_ids: 检索返回的文档 ID 列表
        qrels: {doc_id: relevance_score} (score > 0 视为相关)
        k: 截断位置
    """
    total_relevant = sum(1 for score in qrels.values() if score > 0)
    if total_relevant == 0:
        return 0.0

    relevant_retrieved = sum(
        1 for doc_id in retrieved_doc_ids[:k]
        if qrels.get(doc_id, 0) > 0
    )
    return relevant_retrieved / total_relevant


def mrr_at_k(
    retrieved_doc_ids: list[str],
    qrels: dict[str, int],
    k: int,
) -> float:
    """Mean Reciprocal Rank @ K

    MRR = 1 / rank_of_first_relevant_doc
    """
    for rank, doc_id in enumerate(retrieved_doc_ids[:k], start=1):
        if qrels.get(doc_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def compute_all_metrics(
    retrieved_doc_ids: list[str],
    qrels: dict[str, int],
    k_values: list[int] | None = None,
) -> dict[str, float]:
    """计算所有检索评估指标

    Args:
        retrieved_doc_ids: 检索返回的文档 ID 列表
        qrels: {doc_id: relevance_score}
        k_values: K 值列表，默认 [1, 3, 5, 10]

    Returns:
        {metric_name: value} 字典
    """
    if k_values is None:
        k_values = [1, 3, 5, 10]

    metrics = {}
    for k in k_values:
        metrics[f"NDCG@{k}"] = ndcg_at_k(retrieved_doc_ids, qrels, k)
        metrics[f"Recall@{k}"] = recall_at_k(retrieved_doc_ids, qrels, k)
        metrics[f"Precision@{k}"] = precision_at_k(retrieved_doc_ids, qrels, k)
        metrics[f"MRR@{k}"] = mrr_at_k(retrieved_doc_ids, qrels, k)

    return metrics


def bootstrap_confidence_interval(
    scores: list[float],
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap 置信区间

    Args:
        scores: 逐查询的指标分数列表
        n_bootstrap: Bootstrap 重采样次数
        confidence: 置信水平

    Returns:
        (lower_bound, upper_bound)
    """
    if not scores:
        return (0.0, 0.0)

    means = []
    rng = np.random.RandomState(42)
    n = len(scores)

    for _ in range(n_bootstrap):
        sample = rng.choice(scores, size=n, replace=True)
        means.append(float(np.mean(sample)))

    alpha = (1 - confidence) / 2
    lower = np.percentile(means, alpha * 100)
    upper = np.percentile(means, (1 - alpha) * 100)

    return (float(lower), float(upper))
