"""
Cross-Encoder 重排序模块。

在混合检索后对 top-N 候选 chunks 进行精细重排序，
显著提升 RAG 答案质量。

默认使用 BAAI/bge-reranker-v2-m3（多语言，支持中英文），
也支持通过环境变量配置其他 Cross-Encoder 模型。

用法:
    from retrieval.reranker import Reranker

    reranker = Reranker()
    reranked = reranker.rerank(query, chunks, top_k=5)
"""

import os
from functools import lru_cache
from typing import List, Dict, Optional


# ─── 默认模型配置 ────────────────────────────────────────

_DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
_MODELSCOPE_RERANKER_ID = "BAAI/bge-reranker-v2-m3"

# 候选池大小：从原始检索取 top N 送入 reranker 精排
_DEFAULT_CANDIDATE_POOL_SIZE = 20


def _get_model_name() -> str:
    return os.environ.get("RERANKER_MODEL_NAME", _DEFAULT_RERANKER_MODEL)


def _is_offline_mode() -> bool:
    flags = (
        os.environ.get("TRANSFORMERS_OFFLINE", ""),
        os.environ.get("HF_HUB_OFFLINE", ""),
    )
    return any(v.strip().lower() in {"1", "true", "yes"} for v in flags)


@lru_cache(maxsize=1)
def _get_reranker_model():
    """懒加载 Cross-Encoder 模型（仅加载一次）。

    下载策略：先尝试 HuggingFace（或 HF_ENDPOINT 镜像），
    若不可达则走 ModelScope。
    """
    from sentence_transformers import CrossEncoder

    model_name = _get_model_name()
    local_path = os.environ.get("RERANKER_MODEL_PATH", "").strip()
    offline = _is_offline_mode()

    if local_path:
        if not os.path.exists(local_path):
            raise RuntimeError(f"RERANKER_MODEL_PATH 不存在: {local_path}")
        model = CrossEncoder(local_path)
        print(f"Reranker 模型已加载（本地路径）: {local_path}")
        return model

    # 先尝试直接加载（HF / HF_ENDPOINT 镜像）
    try:
        model = CrossEncoder(model_name, local_files_only=offline)
    except Exception as e:
        if offline:
            raise RuntimeError(
                f"离线模式下未能从本地缓存加载 Reranker 模型 {model_name}，"
                "请设置 RERANKER_MODEL_PATH 到本地模型目录"
            ) from e
        print(f"HuggingFace 加载 Reranker 失败 ({e})，切换到 ModelScope 下载...")
        try:
            from modelscope import snapshot_download
            print(f"正在通过 ModelScope 下载 Reranker 模型 {_MODELSCOPE_RERANKER_ID}...")
            local_path = snapshot_download(_MODELSCOPE_RERANKER_ID)
            print(f"Reranker 模型已下载到: {local_path}")
            model = CrossEncoder(local_path)
        except ImportError:
            raise RuntimeError(
                f"无法加载 Reranker 模型 {model_name}，且 modelscope 不可用。"
                "请手动下载模型并设置 RERANKER_MODEL_PATH 环境变量"
            )
    else:
        print(f"Reranker 模型已加载: {model_name}")

    return model


class Reranker:
    """Cross-Encoder 重排序器。

    在检索管线中位于混合检索之后、上下文组装之前，
    对候选 chunks 做精细语义匹配排序。

    Usage:
        reranker = Reranker()
        top_chunks = reranker.rerank(
            query="如何配置 Milvus？",
            chunks=[{"chunk_text": "...", "score": 0.85}, ...],
            top_k=5,
            candidate_pool_size=15,
        )
    """

    # 默认禁用 — 通过环境变量 RERANK_ENABLED=true 开启
    _DEFAULT_ENABLED = False

    def __init__(
        self,
        candidate_pool_size: int = _DEFAULT_CANDIDATE_POOL_SIZE,
        fusion_weight: float = 0.7,
    ):
        self._candidate_pool_size = candidate_pool_size
        # 融合权重：rerank 分数权重，1-weight 为原始分数权重
        self._fusion_weight = max(0.0, min(1.0, fusion_weight))

    @property
    def enabled(self) -> bool:
        """是否启用 reranking（通过环境变量控制）"""
        val = os.environ.get("RERANK_ENABLED", "").strip().lower()
        if val in {"1", "true", "yes", "on"}:
            return True
        return self._DEFAULT_ENABLED

    @property
    def candidate_pool_size(self) -> int:
        return self._candidate_pool_size

    def rerank(
        self,
        query: str,
        chunks: List[Dict],
        top_k: int = 5,
        candidate_pool_size: Optional[int] = None,
    ) -> List[Dict]:
        """对候选 chunks 重排序并返回 top_k。

        Args:
            query: 用户查询
            chunks: 检索结果列表，每项必须有 "chunk_text" 字段
            top_k: 最终返回数量
            candidate_pool_size: 送入 reranker 的候选池大小（取前 N 个）

        Returns:
            重排序后的 chunks，附带 rerank_score 字段
        """
        if not self.enabled or not chunks:
            return chunks[:top_k]

        pool_size = candidate_pool_size or self._candidate_pool_size
        candidates = chunks[:pool_size]

        if len(candidates) <= 1:
            return candidates[:top_k]

        try:
            model = _get_reranker_model()
        except Exception as e:
            print(f"⚠ Reranker 模型加载失败，跳过重排序: {e}")
            return chunks[:top_k]

        # 构建 (query, chunk_text) 对
        pairs = [(query, ch.get("chunk_text", "")) for ch in candidates]

        try:
            scores = model.predict(pairs, show_progress_bar=False)
        except Exception as e:
            print(f"⚠ Reranker 预测失败，跳过重排序: {e}")
            return chunks[:top_k]

        # 将 rerank 分数写入候选
        for ch, score in zip(candidates, scores):
            ch["rerank_score"] = float(score)

        # 按 rerank 分数降序排列
        candidates.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)

        # 对 rerank 分数做归一化
        rerank_scores = [ch.get("rerank_score", 0.0) for ch in candidates]
        mn, mx = min(rerank_scores), max(rerank_scores)
        if mx - mn > 1e-12:
            for ch in candidates:
                ch["rerank_score"] = (ch["rerank_score"] - mn) / (mx - mn)

        # 融合原始分数和 rerank 分数（权重可配置）
        w = self._fusion_weight
        for ch in candidates:
            original_score = ch.get("score", 0.0)
            rerank_score = ch.get("rerank_score", 0.0)
            ch["score"] = (1.0 - w) * original_score + w * rerank_score

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]
