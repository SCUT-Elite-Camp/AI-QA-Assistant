"""双路混合检索 + 图谱扩展

完整的 A-MEM 风格检索管道:
1. Card Dense + BM25 → RRF
2. Segment Dense + BM25 → RRF (Path B fallback)
3. Cross-source merge (prioritize cards over segments)
4. 2-hop BFS graph expansion (follow card links)
5. Heat/recency boost
6. Deduplication

最终返回统一排序的检索结果。
"""

import logging
import math
from collections import deque
from datetime import datetime
from typing import Optional

import numpy as np

from knowledge_cards.schemas import KnowledgeCard
from knowledge_cards.card_store import CardStore

logger = logging.getLogger(__name__)


class RetrievalResult:
    """统一的检索结果条目"""

    def __init__(
        self,
        result_id: str,
        content: str,
        score: float,
        source_type: str,          # "card" | "segment"
        doc_id: str = "",
        card_id: str = "",
        segment_id: str = "",
        keywords: list[str] | None = None,
        tags: list[str] | None = None,
        retrieval_count: int = 0,
        last_accessed: str | None = None,
        link_ids: list[str] | None = None,
    ):
        self.id = result_id
        self.content = content
        self.score = score
        self.source_type = source_type
        self.doc_id = doc_id
        self.card_id = card_id
        self.segment_id = segment_id
        self.keywords = keywords or []
        self.tags = tags or []
        self.retrieval_count = retrieval_count
        self.last_accessed = last_accessed
        self.link_ids = link_ids or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "score": self.score,
            "source_type": self.source_type,
            "doc_id": self.doc_id,
            "card_id": self.card_id,
            "segment_id": self.segment_id,
            "keywords": self.keywords,
            "tags": self.tags,
        }


class CardRetriever:
    """知识卡片双路检索器

    检索管道:
    1. Dense vector search (cards + segments)
    2. BM25 sparse search (cards + segments)
    3. RRF merge (dense + bm25, separately per source)
    4. Cross-source merge (cards RRF + segments RRF)
    5. 2-hop BFS graph expansion
    6. Heat/recency boost
    7. Dedup → rank → return top_k
    """

    def __init__(
        self,
        card_store: CardStore,
        embedding_fn=None,          # 查询编码函数
        bm25_card_index=None,       # 卡片 BM25 索引
        bm25_segment_index=None,    # 段落 BM25 索引
        rrf_k: int = 60,
        graph_expansion_hops: int = 2,
        graph_expansion_cap: int = 8,
        graph_similarity_gate: float = 0.25,
        heat_alpha: float = 0.05,
        card_weight: float = 0.6,
        segment_weight: float = 0.4,
    ):
        self.card_store = card_store
        self.embedding_fn = embedding_fn
        self.bm25_card_index = bm25_card_index
        self.bm25_segment_index = bm25_segment_index

        # RRF
        self.rrf_k = rrf_k

        # Graph expansion
        self.graph_hops = graph_expansion_hops
        self.graph_cap = graph_expansion_caps = graph_expansion_cap
        self.graph_gate = graph_similarity_gate

        # Scoring
        self.heat_alpha = heat_alpha
        self.card_weight = card_weight
        self.segment_weight = segment_weight

    # ================================================================
    # 主检索入口
    # ================================================================

    async def search(
        self,
        query: str,
        top_k: int = 10,
        search_cards: bool = True,
        search_segments: bool = True,
        expand_graph: bool = True,
    ) -> list[RetrievalResult]:
        """主检索入口

        Args:
            query: 用户查询文本
            top_k: 最终返回数量
            search_cards: 是否检索卡片
            search_segments: 是否检索段落
            expand_graph: 是否做图谱扩展

        Returns:
            统一排序的检索结果列表
        """
        # 1. 编码查询
        query_embedding = None
        if self.embedding_fn:
            query_embedding = self.embedding_fn([query])[0]
            query_embedding = np.array(query_embedding)

        # 2. 双路检索
        all_dense = []
        all_bm25 = []

        if search_cards and query_embedding is not None:
            card_dense = await self.card_store.search_cards(
                query_embedding.tolist(), top_k=top_k * 2
            )
            all_dense.extend([
                RetrievalResult(
                    result_id=r.get("card_id", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    source_type="card",
                    card_id=r.get("card_id", ""),
                    doc_id=r.get("doc_id", ""),
                ) for r in card_dense
            ])

        if search_segments and query_embedding is not None:
            seg_dense = await self.card_store.search_segments(
                query_embedding.tolist(), top_k=top_k * 2
            )
            all_dense.extend([
                RetrievalResult(
                    result_id=r.get("segment_id", ""),
                    content=r.get("text", ""),
                    score=r.get("score", 0.0),
                    source_type="segment",
                    segment_id=r.get("segment_id", ""),
                    doc_id=r.get("doc_id", ""),
                ) for r in seg_dense
            ])

        # BM25（如果有索引）
        if self.bm25_card_index:
            bm25_cards = self.bm25_card_index.search(query, top_k * 2)
            all_bm25.extend([
                RetrievalResult(
                    result_id=r.get("card_id", r.get("id", "")),
                    content=r.get("content", r.get("text", "")),
                    score=r.get("score", 0.0),
                    source_type="card",
                ) for r in bm25_cards
            ])

        if self.bm25_segment_index:
            bm25_segs = self.bm25_segment_index.search(query, top_k * 2)
            all_bm25.extend([
                RetrievalResult(
                    result_id=r.get("segment_id", r.get("id", "")),
                    content=r.get("content", r.get("text", "")),
                    score=r.get("score", 0.0),
                    source_type="segment",
                ) for r in bm25_segs
            ])

        # 3. RRF merge
        merged = self._rrf_merge(all_dense, all_bm25)

        # 4. Cross-source merge (cards preferred)
        merged = self._cross_source_merge(merged)

        # 5. Graph expansion
        if expand_graph and query_embedding is not None:
            merged = await self._graph_expand(merged, query_embedding)

        # 6. Heat/recency boost
        merged = self._heat_boost(merged)

        # 7. Dedup + sort
        merged = self._deduplicate_and_sort(merged)

        return merged[:top_k]

    # ================================================================
    # RRF Merge
    # ================================================================

    def _rrf_merge(
        self,
        dense_results: list[RetrievalResult],
        bm25_results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Reciprocal Rank Fusion

        RRF_score(r) = sum_{source} 1/(k + rank(r))
        """
        scores: dict[str, tuple[RetrievalResult, float]] = {}

        # Dense
        for rank, r in enumerate(sorted(dense_results, key=lambda x: x.score, reverse=True)):
            key = r.id
            if key not in scores:
                scores[key] = (r, 0.0)
            scores[key] = (scores[key][0], scores[key][1] + 1.0 / (self.rrf_k + rank + 1))

        # BM25
        for rank, r in enumerate(sorted(bm25_results, key=lambda x: x.score, reverse=True)):
            key = r.id
            if key not in scores:
                scores[key] = (r, 0.0)
            scores[key] = (scores[key][0], scores[key][1] + 1.0 / (self.rrf_k + rank + 1))

        merged = []
        for result, rrf_score in scores.values():
            result.score = rrf_score
            merged.append(result)

        return sorted(merged, key=lambda x: x.score, reverse=True)

    # ================================================================
    # Cross-source merge
    # ================================================================

    def _cross_source_merge(
        self, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """卡片优先去重: 如果 card 和 segment 包含相同内容，保留 card"""
        cards = [r for r in results if r.source_type == "card"]
        segments = [r for r in results if r.source_type == "segment"]

        merged = []
        seen_content_hashes = set()

        # 先加卡片（更高优先级）
        for r in sorted(cards, key=lambda x: x.score, reverse=True):
            ch = hash(r.content[:100])  # 简单内容去重
            if ch not in seen_content_hashes:
                seen_content_hashes.add(ch)
                r.score *= self.card_weight
                merged.append(r)

        # 再加段落
        for r in sorted(segments, key=lambda x: x.score, reverse=True):
            ch = hash(r.content[:100])
            if ch not in seen_content_hashes:
                seen_content_hashes.add(ch)
                r.score *= self.segment_weight
                merged.append(r)

        return sorted(merged, key=lambda x: x.score, reverse=True)

    # ================================================================
    # Graph Expansion (2-hop BFS)
    # ================================================================

    async def _graph_expand(
        self,
        results: list[RetrievalResult],
        query_embedding: np.ndarray,
    ) -> list[RetrievalResult]:
        """2-hop BFS on card link graph

        从 anchor cards 出发，遍历链接卡片。
        相关性门控: cosine(query, card_embedding) >= graph_gate (0.25)
        最大扩展: graph_cap (8) 个图节点
        获取实际卡片内容填充到结果中。
        """
        cards = [r for r in results if r.source_type == "card"]
        if not cards:
            return results

        visited = set(r.id for r in cards)
        graph_results = []
        frontier = deque()

        # 获取 embedding 函数用于门控
        embed_fn = self.embedding_fn

        # 初始化 BFS 队列
        for r in cards:
            if r.card_id:
                frontier.append((r.card_id, 0, r.score))

        # 收集需要查询的卡片 ID
        candidate_ids = []
        while frontier:
            card_id, hop, anchor_score = frontier.popleft()
            if hop >= self.graph_hops:
                continue

            linked_ids = self.card_store.get_linked_card_ids(card_id)
            for lid in linked_ids:
                if lid in visited:
                    continue
                visited.add(lid)
                candidate_ids.append(lid)
                frontier.append((lid, hop + 1, anchor_score * 0.8))

        if not candidate_ids:
            return results

        # 批量从 Milvus 获取卡片详情
        fetched_cards = await self.card_store.get_cards_by_ids(candidate_ids)
        if not fetched_cards:
            return results

        # 相关性门控 + 填充内容
        expanded_count = 0
        for lid in candidate_ids:
            if expanded_count >= self.graph_cap:
                break

            card_data = fetched_cards.get(lid)
            if not card_data or not card_data.get("content"):
                continue

            content = card_data["content"]

            # 相关性门控：用查询和卡片内容的 embedding 相似度过滤
            if embed_fn and query_embedding is not None:
                try:
                    card_emb = np.array(embed_fn([content])[0])
                    sim = float(
                        np.dot(query_embedding, card_emb)
                        / (np.linalg.norm(query_embedding) * np.linalg.norm(card_emb))
                    )
                    if sim < self.graph_gate:
                        continue
                except Exception:
                    pass  # embedding 失败则跳过门控，保留该卡片

            keywords = card_data.get("keywords", [])
            tags = card_data.get("tags", [])
            doc_id = card_data.get("doc_id", "")

            # 为图扩展卡片计算衰减分数
            # (cid, hop, anchor_score) 已在前面的 BFS 中记录在 candidate_ids 列表
            decay_score = 0.3  # 默认衰减分数

            graph_results.append(RetrievalResult(
                result_id=lid,
                content=content,
                score=decay_score,
                source_type="card",
                card_id=lid,
                doc_id=doc_id,
                keywords=keywords,
                tags=tags,
                link_ids=[lid],
            ))
            expanded_count += 1

        return results + graph_results

    # ================================================================
    # Heat/Recency Boost
    # ================================================================

    def _heat_boost(
        self, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """热度加权: score *= (1 + alpha * ln(1 + retrieval_count) / (age_days + 1))

        经常被检索的卡片获得提升，随时间衰减。
        """
        now = datetime.now()
        for r in results:
            boost = 1.0
            if r.retrieval_count > 0:
                heat = math.log(1 + r.retrieval_count)
                boost += self.heat_alpha * heat

            if r.last_accessed:
                try:
                    last = datetime.fromisoformat(r.last_accessed)
                    age_days = max(0, (now - last).days)
                    boost /= (age_days + 1)
                except (ValueError, TypeError):
                    pass

            r.score *= boost

        return results

    # ================================================================
    # Dedup
    # ================================================================

    def _deduplicate_and_sort(
        self, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """去重 + 排序"""
        seen = set()
        unique = []
        for r in sorted(results, key=lambda x: x.score, reverse=True):
            if r.id not in seen:
                seen.add(r.id)
                unique.append(r)
        return unique

    # ================================================================
    # 便捷方法
    # ================================================================

    async def search_cards_only(
        self, query: str, top_k: int = 10
    ) -> list[RetrievalResult]:
        """仅检索知识卡片"""
        return await self.search(
            query=query,
            top_k=top_k,
            search_cards=True,
            search_segments=False,
            expand_graph=False,
        )

    async def search_agentic(
        self, query: str, top_k: int = 10
    ) -> list[RetrievalResult]:
        """带图谱扩展的检索（A-MEM search_agentic 对应）"""
        return await self.search(
            query=query,
            top_k=top_k,
            search_cards=True,
            search_segments=True,
            expand_graph=True,
        )
