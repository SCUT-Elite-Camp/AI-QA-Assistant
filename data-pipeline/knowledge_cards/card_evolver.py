"""卡片演化模块 — P_s3

A-MEM Memory Evolution:
当新卡片与已有卡片的相似度在 borderline 范围（0.72~0.85）时，
LLM 判断处理方式: EVOLVE / CONFLICT / EXPAND / NEW

核心原则（A-MEM 论文）:
- 原始 content 不可变（保证可追溯）
- 仅更新总结层: context, keywords, tags
- evolution_history 记录每次变更
"""

import json
import logging
import urllib.request
import urllib.error
import re
from typing import Optional

import numpy as np

from knowledge_cards.schemas import (
    KnowledgeCard,
    EvolutionRecord,
    EvolutionAction,
)

logger = logging.getLogger(__name__)

# ============================================================
# P_s3 Prompt 模板
# ============================================================

P_S3_SYSTEM = (
    "你是知识库维护者。新卡片与已有卡片高度相似时，判断如何处理。输出纯JSON。"
)

P_S3_USER = """新卡片与已有卡片高度相似，请决定如何处理。

已有卡片 [{existing_id}]:
内容: {existing_content}
关键词: {existing_keywords}
描述: {existing_context}
标签: {existing_tags}

新卡片:
内容: {new_content}
关键词: {new_keywords}
描述: {new_context}
标签: {new_tags}

两张卡相似度: {similarity:.3f}

输出纯JSON：
{{
  "action": "evolve",
  "reason": "判断理由",
  "new_context": "更新后的描述（仅evolve/expand时需要）",
  "new_keywords": ["新关键词列表（仅evolve/expand时需要）"],
  "new_tags": ["新标签列表（仅evolve/expand时需要）"]
}}

action 选项：
- evolve: 新信息修正/深化已有卡片 → 更新context/keywords/tags
- conflict: 新旧矛盾但各有依据 → 标记冲突，都保留
- expand: 新信息补充已有卡片 → 合并扩展
- new: 虽相似但讨论不同方面 → 保持独立"""


class CardEvolver:
    """卡片演化管理器

    规则（来自 A-MEM）:
    - cosine 0.72~0.85: borderline → LLM 判断
    - cosine < 0.72: 独立卡片，不演化
    - cosine > 0.85: 高度相似，LLM 判断（通常 merge）

    每次最多演化 3 个邻居卡片。
    """

    def __init__(
        self,
        cosine_min: float = 0.72,
        cosine_max: float = 0.85,
        max_neighbors: int = 3,
        llm_base_url: str = "http://127.0.0.1:11434/v1",
        llm_model: str = "llama3.1",
        llm_timeout: int = 60,
    ):
        self.cosine_min = cosine_min
        self.cosine_max = cosine_max
        self.max_neighbors = max_neighbors
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_timeout = llm_timeout

    def evolve(
        self,
        new_cards: list[KnowledgeCard],
        existing_embeddings: dict[str, np.ndarray],
        existing_card_map: dict[str, KnowledgeCard],
    ) -> list[KnowledgeCard]:
        """检查新卡片是否需要演化已有卡片

        Args:
            new_cards: 新创建的卡片
            existing_embeddings: 已有卡片的 {card_id: embedding}
            existing_card_map: 已有卡片的 {card_id: KnowledgeCard}（会被原地修改）

        Returns:
            处理后的新卡片列表（未被吸收的才返回）
        """
        kept_new_cards = []

        for card in new_cards:
            if card.embedding is None:
                kept_new_cards.append(card)
                continue

            card_emb = np.array(card.embedding)

            # 找到 borderline 范围内的已有卡片
            candidates = self._find_borderline(
                card_emb, existing_embeddings
            )

            if not candidates:
                kept_new_cards.append(card)
                continue

            # 最多处理 max_neighbors 个
            absorbed = False
            for existing_id, sim_score in candidates[: self.max_neighbors]:
                existing_card = existing_card_map.get(existing_id)
                if existing_card is None:
                    continue

                action, updates = self._judge_evolution(
                    existing_card, card, sim_score
                )

                if action == EvolutionAction.EVOLVE:
                    self._apply_evolution(existing_card, card, updates)
                    absorbed = True

                elif action == EvolutionAction.EXPAND:
                    self._apply_expansion(existing_card, card, updates)
                    absorbed = True

                elif action == EvolutionAction.CONFLICT:
                    existing_card.is_conflict = True
                    card.is_conflict = True
                    # 两者都保留

                # action == NEW: 两者都保留，什么都不做

            if not absorbed:
                kept_new_cards.append(card)

        return kept_new_cards

    def _find_borderline(
        self,
        query_emb: np.ndarray,
        existing_embeddings: dict[str, np.ndarray],
    ) -> list[tuple[str, float]]:
        """找到 borderlin 相似度范围内的已有卡片"""
        candidates = []
        for card_id, emb in existing_embeddings.items():
            sim = self._cosine_sim(query_emb, emb)
            if self.cosine_min <= sim <= self.cosine_max:
                candidates.append((card_id, float(sim)))
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def _judge_evolution(
        self,
        existing: KnowledgeCard,
        new: KnowledgeCard,
        sim: float,
    ) -> tuple[EvolutionAction, dict]:
        """LLM 判断演化类型"""
        prompt = P_S3_USER.format(
            existing_id=existing.card_id,
            existing_content=existing.content[:500],
            existing_keywords=", ".join(existing.keywords),
            existing_context=existing.context[:200],
            existing_tags=", ".join(existing.tags),
            new_content=new.content[:500],
            new_keywords=", ".join(new.keywords),
            new_context=new.context[:200],
            new_tags=", ".join(new.tags),
            similarity=sim,
        )

        raw_response = self._call_llm(P_S3_SYSTEM, prompt)
        data = self._parse_json(raw_response)

        action_str = data.get("action", "new")
        try:
            action = EvolutionAction(action_str)
        except ValueError:
            action = EvolutionAction.NEW

        updates = {
            "new_context": data.get("new_context", ""),
            "new_keywords": data.get("new_keywords", []),
            "new_tags": data.get("new_tags", []),
            "reason": data.get("reason", ""),
        }

        return action, updates

    @staticmethod
    def _apply_evolution(
        existing: KnowledgeCard,
        new: KnowledgeCard,
        updates: dict,
    ):
        """应用 EVOLVE 操作：用新信息更新已有卡片"""
        # 记录演化历史
        for field in ["context", "keywords", "tags"]:
            old_val = getattr(existing, field)

            new_key = f"new_{field}"
            if new_key in updates and updates[new_key]:
                new_val = updates[new_key]

                if isinstance(old_val, list):
                    old_val_str = ", ".join(old_val)
                    new_val_str = ", ".join(new_val) if isinstance(new_val, list) else str(new_val)
                else:
                    old_val_str = str(old_val)
                    new_val_str = str(new_val)

                if old_val_str != new_val_str:
                    existing.evolution_history.append(EvolutionRecord(
                        trigger_card_id=new.card_id,
                        field_changed=field,
                        old_value=old_val_str,
                        new_value=new_val_str,
                        evolution_type=EvolutionAction.EVOLVE,
                        reason=updates.get("reason", ""),
                    ))

                    # 更新字段
                    if field == "context" and updates["new_context"]:
                        existing.context = updates["new_context"]
                    elif field == "keywords" and updates["new_keywords"]:
                        existing.keywords = updates["new_keywords"]
                    elif field == "tags" and updates["new_tags"]:
                        existing.tags = updates["new_tags"]

        existing.is_evolved = True

    @staticmethod
    def _apply_expansion(
        existing: KnowledgeCard,
        new: KnowledgeCard,
        updates: dict,
    ):
        """应用 EXPAND 操作：合并新卡片内容到已有卡片"""
        # 记录
        existing.evolution_history.append(EvolutionRecord(
            trigger_card_id=new.card_id,
            field_changed="context",
            old_value=existing.context,
            new_value=updates.get("new_context", existing.context),
            evolution_type=EvolutionAction.EXPAND,
            reason=updates.get("reason", ""),
        ))

        if updates.get("new_context"):
            existing.context = updates["new_context"]
        if updates.get("new_keywords"):
            # 合并关键词（去重）
            merged = list(dict.fromkeys(existing.keywords + updates["new_keywords"]))
            existing.keywords = merged[:8]  # 最多 8 个
        if updates.get("new_tags"):
            merged = list(dict.fromkeys(existing.tags + updates["new_tags"]))
            existing.tags = merged[:5]

        existing.is_evolved = True
        # 将新卡片的来源段合并到已有卡片
        for seg_id in new.source_segments:
            if seg_id not in existing.source_segments:
                existing.source_segments.append(seg_id)

    def _call_llm(self, system: str, user_prompt: str) -> str:
        """调用 LLM"""
        url = f"{self.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        headers = {"Content-Type": "application/json"}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.llm_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"LLM evolution judge failed: {e}")
            # 默认行为：如果 LLM 不可用，高相似度 → evolve
            return '{"action": "evolve", "reason": "auto (LLM unavailable)"}'

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        return float(dot / norm) if norm > 0 else 0.0
