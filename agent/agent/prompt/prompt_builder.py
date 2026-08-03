from typing import Any, Optional

from agent.prompt.templates import (
    ANSWER_RULES,
    SYSTEM_ROLE,
    DUAL_SYSTEM_ROLE,
    DUAL_ANSWER_RULES,
)


class PromptBuilder:
    """RAG Prompt 构建器

    支持两种格式:
    - build(): 传统单一上下文（向后兼容）
    - build_dual(): 知识卡片 + 原文片段双格式（A-MEM agentic 检索）
    """

    def build(self, query: str, context: str = "") -> str:
        """传统 Prompt：单一上下文格式（向后兼容）"""
        return f"""{SYSTEM_ROLE}

用户问题：
{query}

检索上下文：
{context}

严格约束：
{ANSWER_RULES}
"""

    def build_dual(
        self,
        query: str,
        cards_context: str = "",
        segments_context: str = "",
    ) -> str:
        """双格式 Prompt：知识卡片 + 原文片段

        Args:
            query: 用户问题
            cards_context: [K-N] 格式的知识卡片上下文
            segments_context: [S-N] 格式的原文片段上下文

        Returns:
            完整 Prompt 字符串
        """
        cards_section = (
            cards_context if cards_context else "无相关知识卡片"
        )
        segments_section = (
            segments_context if segments_context else "无相关原文片段"
        )

        return f"""{DUAL_SYSTEM_ROLE}

用户问题：
{query}

知识卡片：
{cards_section}

原文片段：
{segments_section}

严格约束：
{DUAL_ANSWER_RULES}
"""

    def build_context_for_result(
        self,
        index: int,
        source_type: str,
        content: str,
        doc_id: str = "",
        keywords: list[str] | None = None,
        tags: list[str] | None = None,
        score: float = 0.0,
    ) -> str:
        """为单个检索结果构建上下文条目

        Args:
            index: 引用编号
            source_type: "card" 或 "segment"
            content: 文本内容
            doc_id: 来源文档 ID
            keywords: 卡片关键词（仅 card）
            tags: 卡片标签（仅 card）
            score: 相关性分数

        Returns:
            格式化的上下文字符串
        """
        if source_type == "card":
            prefix = f"[K-{index}]"
            meta_parts = []
            if keywords:
                meta_parts.append(f"关键词: {', '.join(keywords)}")
            if tags:
                meta_parts.append(f"分类: {', '.join(tags)}")
            meta_line = f" ({'; '.join(meta_parts)})" if meta_parts else ""
            return (
                f"{prefix} (来源: {doc_id}){meta_line}\n"
                f"内容: {content}\n"
                f"相关度: {score:.4f}"
            )
        else:
            prefix = f"[S-{index}]"
            return (
                f"{prefix} (来源: {doc_id})\n"
                f"片段: {content}\n"
                f"相关度: {score:.4f}"
            )
