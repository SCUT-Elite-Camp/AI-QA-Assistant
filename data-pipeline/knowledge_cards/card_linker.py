"""卡片链接模块 — P_s2

A-MEM 两阶段链接算法:
Stage 1: 向量余弦 top-k 预筛选（k=10, min_sim=0.3）
Stage 2: LLM 判断（P_s2 提示），过滤表面相似但语义无关的候选对

输出双向 CardLink 关系存入 SQLite。
"""

import json
import logging
import urllib.request
import urllib.error
import re
from typing import Optional

import numpy as np

from knowledge_cards.schemas import KnowledgeCard, CardLink, LinkType
from knowledge_cards.card_store import CardStore

logger = logging.getLogger(__name__)

# ============================================================
# P_s2 Prompt 模板
# ============================================================

P_S2_SYSTEM = (
    "你是一个知识关联判断器。判断两张知识卡片是否有实质语义关联。输出纯JSON。"
)

P_S2_USER = """分析以下两张知识卡片，判断它们是否具有实质性的语义关联。

卡片A：
  内容: {card_a_content}
  标签: {card_a_tags}
  描述: {card_a_context}

卡片B：
  内容: {card_b_content}
  标签: {card_b_tags}
  描述: {card_b_context}

输出纯JSON：
{{
  "related": true,
  "link_type": "supports",
  "strength": 0.75,
  "reason": "关联理由"
}}

关联类型：
- elaborates: B详细阐述了A
- contradicts: B与A信息矛盾
- supports: B为A提供佐证
- precedes: A在时间/逻辑顺序上先于B
- example_of: B是A的一个具体例子"""


class CardLinker:
    """卡片链接器

    两阶段:
    1. 向量 top-k 预筛选 — 减少 LLM 判断的候选对（从 O(N²) 降到 O(N*k)）
    2. LLM judge — 过滤表面相似，识别深层关联
    """

    def __init__(
        self,
        card_store: CardStore,
        top_k: int = 10,
        similarity_min: float = 0.3,
        llm_base_url: str = "http://127.0.0.1:11434/v1",
        llm_model: str = "llama3.1",
        llm_timeout: int = 60,
    ):
        self.card_store = card_store
        self.top_k = top_k
        self.similarity_min = similarity_min
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_timeout = llm_timeout

    def link_cards(
        self,
        new_cards: list[KnowledgeCard],
        existing_card_embeddings: Optional[dict[str, np.ndarray]] = None,
    ) -> tuple[list[KnowledgeCard], list[CardLink]]:
        """为新卡片建立与已有卡片库的链接

        Args:
            new_cards: 新创建的卡片列表
            existing_card_embeddings: 已有卡片的 {card_id: embedding} 映射
                                      如果为 None，则不与新卡片之外的卡片链接

        Returns:
            (更新后的 cards（links 字段已填充）, 新增的 CardLink 列表)
        """
        all_links = []

        # 构建新卡片嵌入索引
        new_embeddings = {}
        for card in new_cards:
            if card.embedding:
                new_embeddings[card.card_id] = np.array(card.embedding)

        # 合并已有卡片嵌入（如果有）
        all_embeddings = {}
        if existing_card_embeddings:
            all_embeddings.update(existing_card_embeddings)
        all_embeddings.update(new_embeddings)

        if len(all_embeddings) < 2:
            return new_cards, []

        # 对每张新卡片，找 top-k 最近邻
        for card in new_cards:
            if card.embedding is None:
                continue

            card_emb = np.array(card.embedding)
            candidates = self._vector_top_k(
                card_emb=card_emb,
                card_id=card.card_id,
                all_embeddings=all_embeddings,
            )

            # Stage 2: LLM judge
            for candidate_id, sim_score in candidates:
                # 找 candidate 的卡片对象
                candidate_card = self._find_card(candidate_id, new_cards)
                if candidate_card is None:
                    continue

                link = self._judge_link(card, candidate_card, sim_score)
                if link:
                    card.links.append(candidate_id)
                    all_links.append(link)

                    # 双向链接（同时更新对端）
                    candidate_card.links.append(card.card_id)

        return new_cards, all_links

    def _vector_top_k(
        self,
        card_emb: np.ndarray,
        card_id: str,
        all_embeddings: dict[str, np.ndarray],
    ) -> list[tuple[str, float]]:
        """Stage 1: 余弦相似度 top-k 预筛选"""
        scores = []
        for other_id, other_emb in all_embeddings.items():
            if other_id == card_id:
                continue
            sim = self._cosine_sim(card_emb, other_emb)
            if sim >= self.similarity_min:
                scores.append((other_id, sim))

        # 按相似度降序，取 top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[: self.top_k]

    def _judge_link(
        self,
        card_a: KnowledgeCard,
        card_b: KnowledgeCard,
        sim_score: float,
    ) -> Optional[CardLink]:
        """Stage 2: LLM 判断链接是否成立

        Returns:
            CardLink 如果 LLM 确认关联，否则 None
        """
        prompt = P_S2_USER.format(
            card_a_content=card_a.content[:500],
            card_a_tags=", ".join(card_a.tags),
            card_a_context=card_a.context[:200],
            card_b_content=card_b.content[:500],
            card_b_tags=", ".join(card_b.tags),
            card_b_context=card_b.context[:200],
        )

        raw_response = self._call_llm(P_S2_SYSTEM, prompt)
        data = self._parse_json(raw_response)

        if data.get("related", False):
            return CardLink(
                source_id=card_a.card_id,
                target_id=card_b.card_id,
                link_type=data.get("link_type", "supports"),
                strength=data.get("strength", sim_score),
                reason=data.get("reason", ""),
            )

        return None

    def link_batch_simple(
        self,
        cards: list[KnowledgeCard],
    ) -> list[CardLink]:
        """简化版：只做向量 top-k（跳过 LLM judge）

        用于快速链接或 LLM 不可用的场景。
        """
        links = []
        embeddings = {}
        for card in cards:
            if card.embedding:
                embeddings[card.card_id] = np.array(card.embedding)

        for i, card_a in enumerate(cards):
            if card_a.embedding is None:
                continue
            emb_a = np.array(card_a.embedding)

            for j in range(i + 1, len(cards)):
                card_b = cards[j]
                if card_b.embedding is None:
                    continue
                emb_b = np.array(card_b.embedding)
                sim = self._cosine_sim(emb_a, emb_b)

                if sim >= self.similarity_min:
                    link = CardLink(
                        source_id=card_a.card_id,
                        target_id=card_b.card_id,
                        link_type="supports",
                        strength=float(sim),
                        reason=f"cosine similarity: {sim:.3f}",
                    )
                    links.append(link)
                    card_a.links.append(card_b.card_id)
                    card_b.links.append(card_a.card_id)

        return links

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
            "max_tokens": 256,
        }
        headers = {"Content-Type": "application/json"}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.llm_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"LLM link judge failed: {e}")
            return "{}"

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """解析 LLM JSON 响应"""
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

    @staticmethod
    def _find_card(
        card_id: str,
        cards: list[KnowledgeCard],
    ) -> Optional[KnowledgeCard]:
        for card in cards:
            if card.card_id == card_id:
                return card
        return None
