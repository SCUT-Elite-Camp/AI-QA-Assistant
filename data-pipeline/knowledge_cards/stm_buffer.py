"""STM 短期记忆缓冲区（LightMem 核心设计）

核心设计:
- 维护 stm_buffers: Dict[topic_id, TopicBuffer]
- 主题分割模块为每段分配 topic_id
- 同一 topic_id 的段落始终进入同一个独立 buffer
- 每个 buffer 独立追踪 token 数，独立触发 flush
- 文档结束时 flush_all() 清空所有 buffer

对应 LightMem 的 Light2 (Short-Term Memory) 阶段。
"""

import logging
from typing import Optional

from segmenter.base import SemanticSegment
from knowledge_cards.schemas import KnowledgeCard

logger = logging.getLogger(__name__)


class TopicBuffer:
    """单个 topic 的独立缓冲区"""

    def __init__(self, topic_id: str):
        self.topic_id = topic_id
        self.segments: list[SemanticSegment] = []
        self.token_count: int = 0

    def __repr__(self) -> str:
        return (
            f"TopicBuffer(topic={self.topic_id}, "
            f"segments={len(self.segments)}, "
            f"tokens={self.token_count})"
        )


class STMBufferManager:
    """短期记忆缓冲区管理器

    LightMem 的核心设计:
    - 维护 stm_buffers: Dict[topic_id, TopicBuffer]
    - 同一 topic_id 的段落始终进入同一个 buffer
    - 每个 buffer 独立追踪 token 数，独立触发 flush

    用法:
        manager = STMBufferManager(token_threshold=2000)
        for segment in segments:
            cards = manager.add(segment)
            if cards:
                process(cards)
        remaining = manager.flush_all()
    """

    def __init__(
        self,
        token_threshold: int = 2000,
        max_segments_per_batch: int = 15,
        card_constructor=None,
    ):
        """
        Args:
            token_threshold: Token 阈值，单个 buffer 达到后触发 flush
            max_segments_per_batch: 单批次最多段落数（防止超长）
            card_constructor: CardConstructor 实例（延迟注入）
        """
        self.token_threshold = token_threshold
        self.max_segments_per_batch = max_segments_per_batch
        self.card_constructor = card_constructor

        # 核心数据结构: Dict[topic_id, TopicBuffer]
        self.buffers: dict[str, TopicBuffer] = {}

        # 统计
        self.total_segments_added = 0
        self.total_flushes = 0
        self.total_cards_generated = 0

    def add(self, segment: SemanticSegment) -> Optional[list[KnowledgeCard]]:
        """将段落加入其 topic_id 对应的独立缓冲区

        规则:
        - 同一 topic_id → 同一 buffer（无论段落在文档中的位置）
        - 仅当该 buffer 达到 token 阈值时才 flush
        - 跨章节的同话题段落会自动聚合

        Args:
            segment: 带 topic_id 的语义段落

        Returns:
            如果触发了 flush，返回提取的知识卡片列表；否则返回 None
        """
        tid = segment.topic_id
        if not tid:
            logger.warning(f"Segment {segment.segment_id} has no topic_id, generating one")
            tid = f"topic_{segment.segment_id}"
            segment.topic_id = tid

        # 为新 topic 创建独立 buffer
        if tid not in self.buffers:
            self.buffers[tid] = TopicBuffer(topic_id=tid)
            logger.debug(f"New buffer created for topic: {tid}")

        buffer = self.buffers[tid]
        buffer.segments.append(segment)
        self.total_segments_added += 1

        # 估算 token 数（中文: ~1.5 字符/token, 英文: ~4 字符/token）
        estimated_tokens = self._estimate_tokens(segment.text)
        buffer.token_count += estimated_tokens

        # 检查是否达到触发条件:
        # 1. Token 超过阈值
        # 2. 段落数超过限制
        should_flush = (
            buffer.token_count >= self.token_threshold
            or len(buffer.segments) >= self.max_segments_per_batch
        )

        if should_flush:
            logger.info(
                f"Flushing topic '{tid}': "
                f"{len(buffer.segments)} segments, "
                f"~{buffer.token_count} tokens"
            )
            return self.flush_topic(tid)

        return None

    def flush_topic(self, topic_id: str) -> list[KnowledgeCard]:
        """清空指定 topic 的独立缓冲区

        注意: 这里仅构建上下文文本，实际的 LLM 调用在 card_constructor 中进行。
        如果 card_constructor 未注入，返回空列表。
        """
        if topic_id not in self.buffers:
            return []

        buffer = self.buffers.pop(topic_id)
        if not buffer.segments:
            return []

        self.total_flushes += 1

        if self.card_constructor is None:
            logger.warning(
                "No card_constructor injected, returning empty. "
                "Set manager.card_constructor = CardConstructor(...) "
                "before adding segments."
            )
            return []

        # 构建上下文文本（带段边界标记）
        context_text = self._build_context(buffer.segments)

        # 调用 LLM 批量提取
        cards = self.card_constructor.build_cards_batch(
            segments=buffer.segments,
            context_text=context_text,
            topic=buffer.topic_id,
        )

        self.total_cards_generated += len(cards)
        logger.info(
            f"Flushed topic '{topic_id}': "
            f"generated {len(cards)} cards"
        )

        return cards

    def flush_all(self) -> list[KnowledgeCard]:
        """文档处理结束时，flush 所有剩余 buffer

        Returns:
            所有剩余 buffer 产生的卡片合集
        """
        logger.info(
            f"Flushing all {len(self.buffers)} remaining buffers"
        )

        all_cards = []
        for tid in list(self.buffers.keys()):
            cards = self.flush_topic(tid)
            all_cards.extend(cards)

        logger.info(
            f"Flush all complete: {len(all_cards)} cards generated"
        )
        return all_cards

    def _build_context(self, segments: list[SemanticSegment]) -> str:
        """构建带段边界的上下文文本"""
        parts = []
        for i, seg in enumerate(segments):
            parts.append(f"<!-- SEGMENT_{i} -->\n{seg.text}")
        return "\n\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算文本的 token 数

        中文: ~1.5 字符/token
        英文: ~4 字符/token
        混合: 取平均 ~2.5 字符/token（保守估计，防止缓冲区过大）
        """
        chars = len(text)
        if chars == 0:
            return 0
        return max(1, int(chars / 2.0))

    @property
    def buffer_count(self) -> int:
        """当前活跃的缓冲区数量"""
        return len(self.buffers)

    @property
    def status(self) -> dict:
        """返回状态摘要"""
        return {
            "active_buffers": len(self.buffers),
            "total_segments_added": self.total_segments_added,
            "total_flushes": self.total_flushes,
            "total_cards_generated": self.total_cards_generated,
            "buffers_detail": {
                tid: {
                    "segments": buf.token_count,
                    "tokens": buf.token_count,
                }
                for tid, buf in self.buffers.items()
            },
        }
