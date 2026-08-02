"""语义分割模块

基于 LightMem B₂（相似度）方法:
- SimilaritySegmenter: 句子 embedding + 余弦边界检测 + topic 聚类

核心模型:
- SemanticSegment: 语义完整的文本段落，附带 topic_id（用于 STM Dict 缓冲）
"""

from segmenter.base import (
    BaseSegmenter,
    SemanticSegment,
    generate_segment_id,
    generate_topic_id,
)
from segmenter.similarity_segmenter import SimilaritySegmenter
from segmenter.sentence_utils import (
    split_sentences,
    split_sentences_simple,
    merge_short_sentences,
)

__all__ = [
    "BaseSegmenter",
    "SemanticSegment",
    "SimilaritySegmenter",
    "split_sentences",
    "split_sentences_simple",
    "merge_short_sentences",
    "generate_segment_id",
    "generate_topic_id",
]
