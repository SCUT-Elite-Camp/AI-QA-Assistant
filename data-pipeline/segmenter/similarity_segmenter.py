"""LightMem B₂ 语义分割器 + 主题聚类

仅使用 LightMem 的 B₂ (similarity-based) 方法:
- 句子级 embedding → 相邻余弦相似度 → 找断点
- topic_id 分配: 段 embedding 与已有 topic 的均值 embedding 比较，
  相似则复用旧 topic_id，否则创建新 topic

不做 B₁ (attention-based) 因为文档没有对话的 turn 结构。
"""

import logging
from typing import Optional

import numpy as np

from segmenter.base import (
    BaseSegmenter,
    SemanticSegment,
    generate_segment_id,
    generate_topic_id,
)
from segmenter.sentence_utils import (
    split_sentences,
    merge_short_sentences,
)

logger = logging.getLogger(__name__)


class SimilaritySegmenter(BaseSegmenter):
    """基于句子相似度的语义分割器

    对应 LightMem 的 Topic Segmentation B₂ 方法 + topic 聚类。

    算法:
    1. 分句 → sentence embeddings
    2. 计算相邻句子余弦相似度
    3. 标记相似度 < threshold 的位置为边界
    4. 边界之间的句子组成 SemanticSegment
    5. 对每个 segment 的 embedding，与之前所有 topic 的均值 cosine 比较:
       - cosine > topic_reuse_threshold → 复用旧 topic_id
       - 否则 → 创建新 topic_id

    参数:
        similarity_threshold: 断点阈值 (默认 0.65)
        topic_reuse_threshold: topic 复用阈值 (默认 0.80)
        min_sentences: 每段最少句子数 (默认 2)
        embedding_fn: 句子编码函数 (默认用 BGE-small-en-v1.5)
    """

    def __init__(
        self,
        similarity_threshold: float = 0.65,
        topic_reuse_threshold: float = 0.80,
        min_sentences: int = 2,
        embedding_fn=None,
    ):
        self.similarity_threshold = similarity_threshold
        self.topic_reuse_threshold = topic_reuse_threshold
        self.min_sentences = min_sentences
        self._embedding_fn = embedding_fn

        # topic 状态: {topic_id: (avg_embedding, segment_count)}
        self._topic_registry: dict[str, tuple[np.ndarray, int]] = {}

    @property
    def name(self) -> str:
        return "similarity_segmenter"

    def _get_embedding_fn(self):
        """延迟加载 embedding 函数（复用现有的 embedder）"""
        if self._embedding_fn is not None:
            return self._embedding_fn

        # 尝试复用项目现有的 embed_texts
        try:
            from pipeline.embedder import embed_texts

            self._embedding_fn = lambda texts: embed_texts(texts)
            logger.info("Using existing embed_texts() from pipeline.embedder")
        except ImportError:
            # Fallback: 直接加载 sentence-transformers
            logger.info("Loading BGE-small-en-v1.5 directly")

            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("BAAI/bge-small-en-v1.5")

            def _embed(texts):
                embeddings = model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return embeddings.tolist()

            self._embedding_fn = _embed

        return self._embedding_fn

    def segment(
        self,
        text: str,
        doc_id: str = "",
    ) -> list[SemanticSegment]:
        """主分割流程"""
        if not text or not text.strip():
            return []

        # Step 1: 分句
        raw_sentences = split_sentences(text)
        if len(raw_sentences) < self.min_sentences:
            # 文本太短，整体作为一个段落
            return [self._make_segment(
                text=text.strip(),
                sentences=raw_sentences,
                start_idx=0,
                end_idx=len(text),
                topic_id=generate_topic_id(),
                doc_id=doc_id,
                segment_index=0,
                boundary_score=0.0,
            )]

        # Step 2: 合并超短句
        sentences = merge_short_sentences(raw_sentences, min_chars=15)
        if len(sentences) < 2:
            return [self._make_segment(
                text="".join(sentences),
                sentences=sentences,
                start_idx=0,
                end_idx=len(text),
                topic_id=generate_topic_id(),
                doc_id=doc_id,
                segment_index=0,
                boundary_score=0.0,
            )]

        # Step 3: 计算句子 embeddings
        embed_fn = self._get_embedding_fn()
        embeddings = embed_fn(sentences)
        embeddings = np.array(embeddings)

        # Step 4: 相邻句子余弦相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_sim(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        # Step 5: 检测边界（相似度低于阈值的点）
        boundaries = []
        for i, sim in enumerate(similarities):
            if sim < self.similarity_threshold:
                # boundary_score = 相似度下降幅度
                boundary_score = self.similarity_threshold - sim
                boundaries.append((i + 1, boundary_score))

        # Step 6: 按边界切分为段
        segments = self._split_at_boundaries(
            text=text,
            sentences=sentences,
            embeddings=embeddings,
            boundaries=boundaries,
            doc_id=doc_id,
        )

        return segments

    def _split_at_boundaries(
        self,
        text: str,
        sentences: list[str],
        embeddings: np.ndarray,
        boundaries: list[tuple[int, float]],
        doc_id: str,
    ) -> list[SemanticSegment]:
        """按检测到的边界切分句子组，并为每段分配 topic_id"""
        if not boundaries:
            # 没有明显边界，整体为一个段落
            seg_text = self._join_sentences(sentences)
            return [self._make_segment(
                text=seg_text,
                sentences=sentences,
                start_idx=0,
                end_idx=len(text),
                topic_id=self._assign_topic(embeddings.mean(axis=0)),
                doc_id=doc_id,
                segment_index=0,
                boundary_score=0.0,
            )]

        boundary_positions = set(b[0] for b in boundaries)
        segments = []
        start = 0

        for i in range(1, len(sentences) + 1):
            if i in boundary_positions or i == len(sentences):
                seg_sentences = sentences[start:i]
                seg_text = self._join_sentences(seg_sentences)

                # 计算此段内句子间的平均相似度
                seg_embeddings = embeddings[start:i]
                avg_sim = 1.0
                if len(seg_embeddings) > 1:
                    sims = []
                    for j in range(len(seg_embeddings) - 1):
                        sims.append(self._cosine_sim(
                            seg_embeddings[j], seg_embeddings[j + 1]
                        ))
                    avg_sim = float(np.mean(sims)) if sims else 1.0

                # 计算段边界的 boundary_score
                boundary_score = 0.0
                if start > 0:
                    for bpos, bscore in boundaries:
                        if bpos == start:
                            boundary_score = bscore
                            break

                # 分配 topic_id
                seg_mean_embed = seg_embeddings.mean(axis=0)
                topic_id = self._assign_topic(seg_mean_embed)

                # 更新 topic registry
                if topic_id in self._topic_registry:
                    old_mean, old_count = self._topic_registry[topic_id]
                    new_count = old_count + 1
                    new_mean = (old_mean * old_count + seg_mean_embed) / new_count
                    self._topic_registry[topic_id] = (new_mean, new_count)
                else:
                    self._topic_registry[topic_id] = (seg_mean_embed, 1)

                segment = self._make_segment(
                    text=seg_text,
                    sentences=seg_sentences,
                    start_idx=len(self._join_sentences(sentences[:start])),
                    end_idx=len(
                        self._join_sentences(sentences[:start])) + len(seg_text),
                    topic_id=topic_id,
                    doc_id=doc_id,
                    segment_index=len(segments),
                    boundary_score=boundary_score,
                    avg_similarity=avg_sim,
                )
                segments.append(segment)
                start = i

        return segments

    def _assign_topic(self, embedding: np.ndarray) -> str:
        """为段 embedding 分配 topic_id

        规则:
        - 如果当前段与某个已存在 topic 的平均 embedding 余弦 > threshold → 复用
        - 否则 → 创建新 topic_id
        """
        best_topic = None
        best_sim = 0.0

        for tid, (topic_mean, _) in self._topic_registry.items():
            sim = self._cosine_sim(embedding, topic_mean)
            if sim > best_sim:
                best_sim = sim
                best_topic = tid

        if best_topic and best_sim >= self.topic_reuse_threshold:
            return best_topic
        else:
            return generate_topic_id()

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        """余弦相似度"""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    @staticmethod
    def _join_sentences(sentences: list[str]) -> str:
        """拼接句子为段落文本"""
        return "".join(sentences)

    @staticmethod
    def _make_segment(
        text: str,
        sentences: list[str],
        start_idx: int,
        end_idx: int,
        topic_id: str,
        doc_id: str,
        segment_index: int,
        boundary_score: float = 0.0,
        avg_similarity: float = 1.0,
    ) -> SemanticSegment:
        """创建 SemanticSegment 实例"""
        return SemanticSegment(
            segment_id=generate_segment_id(),
            text=text,
            sentences=sentences,
            start_idx=start_idx,
            end_idx=end_idx,
            avg_similarity=avg_similarity,
            boundary_score=boundary_score,
            topic_id=topic_id,
            doc_id=doc_id,
            segment_index=segment_index,
        )
