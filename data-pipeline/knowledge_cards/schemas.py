"""A-MEM 知识卡片系统数据模型

核心结构:
- KnowledgeCard: 原子知识单元（Zettelkasten 风格卡片）
- CardLink: 两卡之间的语义关联
- EvolutionRecord: 卡片演化审计记录
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举类型
# ============================================================

class CardTag(str, Enum):
    """知识卡片分类标签"""
    FACT = "fact"               # 事实陈述
    DECISION = "decision"       # 决策/决议
    CONSTRAINT = "constraint"   # 约束条件/限制
    EVENT = "event"             # 事件
    DEFINITION = "definition"   # 定义/术语解释
    PROCESS = "process"         # 流程/步骤
    DATA_POINT = "data_point"   # 数据点（数值、统计）


class LinkType(str, Enum):
    """卡片链接类型"""
    ELABORATES = "elaborates"       # B 详细阐述了 A
    CONTRADICTS = "contradicts"     # B 与 A 信息矛盾
    SUPPORTS = "supports"           # B 为 A 提供佐证
    PRECEDES = "precedes"           # A 在时间/逻辑上先于 B
    EXAMPLE_OF = "example_of"       # B 是 A 的具体例子


class EvolutionAction(str, Enum):
    """演化操作类型"""
    EVOLVE = "evolve"       # 新信息修正/深化了已有卡片
    CONFLICT = "conflict"   # 新旧信息矛盾，两者都保留
    EXPAND = "expand"       # 新信息补充了已有卡片
    NEW = "new"             # 与已有卡片无关，保持独立


# ============================================================
# 核心数据模型
# ============================================================

class EvolutionRecord(BaseModel):
    """一次卡片演化操作的审计记录

    原始 content 不变，仅记录 context/keywords/tags 的变化。
    """

    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    trigger_card_id: str = ""       # 触发本次演化的新卡片 ID
    field_changed: str = ""         # 被修改的字段名 (context/keywords/tags)
    old_value: str = ""             # 修改前的值
    new_value: str = ""             # 修改后的值
    evolution_type: EvolutionAction = EvolutionAction.NEW
    reason: str = ""                # LLM 给出的演化理由


class KnowledgeCard(BaseModel):
    """原子知识单元 — Zettelkasten 风格知识卡片

    对应 A-MEM 的 MemoryNote: m_i = {c_i, t_i, K_i, G_i, X_i, e_i, L_i}

    关键设计:
    - content 是原始文本提取物，不可变（保证可追溯）
    - context/keywords/tags 是 LLM 生成的总结层，可在演化时更新
    - embedding 编码了 content+keywords+tags+context 的组合文本
    - links 是双向的，在 SQLite 中冗余存储
    """

    # ---- 标识 ----
    card_id: str = Field(
        default_factory=lambda: f"card_{uuid.uuid4().hex[:12]}"
    )

    # ---- 内容层 ----
    content: str = ""                   # 原始文本中的知识（不可变）
    keywords: list[str] = Field(default_factory=list)   # LLM 提取的检索关键词
    tags: list[str] = Field(default_factory=list)       # 分类标签
    context: str = ""                   # LLM 生成的语义描述（可变，演化时更新）

    # ---- 向量 ----
    embedding: Optional[list[float]] = None  # 384d，编码组合文本，插入 Milvus 后填充

    # ---- 图谱链接 ----
    links: list[str] = Field(default_factory=list)  # 关联卡片 card_id 列表

    # ---- 来源追溯 ----
    doc_id: str = ""                        # 来源文档 MD5
    source_segments: list[str] = Field(     # 来源段落 ID 列表（一张卡可能跨多段）
        default_factory=list
    )

    # ---- 时间戳 ----
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    last_accessed: Optional[str] = None     # 最后被检索的时间

    # ---- 热力统计 ----
    retrieval_count: int = 0                # 被检索次数（用于 heat boost）

    # ---- 演化追踪 ----
    evolution_history: list[EvolutionRecord] = Field(
        default_factory=list
    )
    is_evolved: bool = False                # 是否被后续信息演化过
    is_conflict: bool = False               # 是否与其他卡片存在矛盾

    # ---- 分类 ----
    category: str = "general"               # 高层分类

    def combined_text(self) -> str:
        """组合所有文本字段（用于 embedding 编码）

        与 A-MEM 一致: e_i = Encoder(concat(content, keywords, tags, context))
        """
        kw_text = ", ".join(self.keywords)
        tag_text = ", ".join(self.tags)
        parts = [
            f"content: {self.content}",
            f"keywords: {kw_text}",
            f"tags: {tag_text}",
            f"context: {self.context}",
        ]
        return "\n".join(parts)

    def to_milvus_dict(self) -> dict:
        """转换为 Milvus 插入所需的数据字典"""
        import json

        return {
            "card_id": self.card_id,
            "content": self.content,
            "keywords": json.dumps(self.keywords, ensure_ascii=False),
            "tags": json.dumps(self.tags, ensure_ascii=False),
            "context": self.context,
            "doc_id": self.doc_id,
            "source_segments": json.dumps(
                self.source_segments, ensure_ascii=False
            ),
            "retrieval_count": self.retrieval_count,
            "category": self.category,
            "created_at": int(datetime.now().timestamp()),
        }

    @classmethod
    def from_milvus_hit(cls, hit: dict) -> "KnowledgeCard":
        """从 Milvus 搜索结果构造 KnowledgeCard"""
        import json

        return cls(
            card_id=hit.get("card_id", ""),
            content=hit.get("content", ""),
            keywords=json.loads(hit.get("keywords", "[]")),
            tags=json.loads(hit.get("tags", "[]")),
            context=hit.get("context", ""),
            doc_id=hit.get("doc_id", ""),
            source_segments=json.loads(
                hit.get("source_segments", "[]")
            ),
            retrieval_count=hit.get("retrieval_count", 0),
            category=hit.get("category", "general"),
        )


class CardLink(BaseModel):
    """两卡之间的语义关联

    存储在 SQLite 中，支持双向 BFS 遍历。
    """

    link_id: str = Field(
        default_factory=lambda: f"link_{uuid.uuid4().hex[:12]}"
    )
    source_id: str                      # 源卡片 card_id
    target_id: str                      # 目标卡片 card_id
    link_type: str = "supports"         # 关联类型
    strength: float = 0.5               # 关联强度 0~1
    reason: str = ""                    # LLM 给出的关联理由
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    class Config:
        use_enum_values = True
