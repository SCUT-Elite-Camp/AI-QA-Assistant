"""语义分割模块基类

基于 LightMem 的 B₂（相似度）分割方法，适配文档场景。

核心数据结构:
- SemanticSegment: 语义完整的文本段落，附带 topic_id
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pydantic import BaseModel, Field


def generate_segment_id() -> str:
    """生成唯一的 segment ID"""
    return f"seg_{uuid.uuid4().hex[:12]}"


def generate_topic_id() -> str:
    """生成唯一的 topic ID"""
    return f"topic_{uuid.uuid4().hex[:8]}"


class SemanticSegment(BaseModel):
    """语义完整的文本段落

    由 B₂ 相似度分割算法从文档中切分出来，
    同一 topic_id 的段落共享同一个独立 STM 缓冲区。
    """

    segment_id: str = Field(default_factory=generate_segment_id)
    text: str                                           # 段落的完整文本
    sentences: list[str] = Field(default_factory=list)  # 组成段落的句子列表
    start_idx: int = 0                                  # 在原文中的起始字符位置
    end_idx: int = 0                                    # 在原文中的结束字符位置
    avg_similarity: float = 1.0     # 段落内相邻句子平均余弦相似度
    boundary_score: float = 0.0     # 段前边界的相似度下降幅度 (0~1)
    topic_id: str = ""              # 主题ID（同主题的段进同一STM buffer）
    doc_id: str = ""                # 来源文档ID
    segment_index: int = 0          # 在文档中的序号
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def __repr__(self) -> str:
        preview = self.text[:80].replace("\n", " ")
        return (
            f"SemanticSegment(id={self.segment_id}, "
            f"topic={self.topic_id}, "
            f"len={len(self.text)}chars, "
            f"boundary={self.boundary_score:.2f}, "
            f"text='{preview}...')"
        )


class BaseSegmenter(ABC):
    """语义分割器抽象基类"""

    @abstractmethod
    def segment(
        self,
        text: str,
        doc_id: str = "",
    ) -> list[SemanticSegment]:
        """将文本分割为语义连贯的段落，同时分配 topic_id

        Args:
            text: 原始文档文本
            doc_id: 来源文档MD5

        Returns:
            SemanticSegment 列表，每段带有 topic_id
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """分割器名称"""
        ...
