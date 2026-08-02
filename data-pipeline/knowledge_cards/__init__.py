"""A-MEM 知识卡片系统

核心模块:
- schemas: KnowledgeCard, CardLink, EvolutionRecord 数据模型
- card_store: Milvus + SQLite 存储层
- stm_buffer: Topic-aware STM 缓冲区 (Dict[topic_id, Buffer])
- card_builder: 批量卡片构建 P_s1 (LightMem STM 风格)
- card_linker: 卡片链接 P_s2 (向量 top-k + LLM judge)
- card_evolver: 卡片演化 P_s3 (EVOLVE/CONFLICT/EXPAND/NEW)
- card_retriever: 双路检索 + 图谱扩展 (待实现)
"""

from knowledge_cards.schemas import (
    KnowledgeCard,
    CardLink,
    EvolutionRecord,
    CardTag,
    LinkType,
    EvolutionAction,
)
from knowledge_cards.card_store import CardStore
from knowledge_cards.stm_buffer import STMBufferManager, TopicBuffer
from knowledge_cards.card_builder import CardConstructor
from knowledge_cards.card_linker import CardLinker
from knowledge_cards.card_evolver import CardEvolver

__all__ = [
    # Schemas
    "KnowledgeCard",
    "CardLink",
    "EvolutionRecord",
    "CardTag",
    "LinkType",
    "EvolutionAction",
    # Store
    "CardStore",
    # STM Buffer
    "STMBufferManager",
    "TopicBuffer",
    # Builder
    "CardConstructor",
    # Linker
    "CardLinker",
    # Evolver
    "CardEvolver",
]
