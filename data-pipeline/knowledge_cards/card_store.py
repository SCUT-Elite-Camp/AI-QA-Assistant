"""知识卡片存储层

管理三层存储:
1. Milvus "knowledge_cards" 集合 — 卡片向量检索
2. Milvus "semantic_segments" 集合 — 段落向量检索（Path B fallback）
3. SQLite "card_links" 表 — 卡片链接图谱（双向关系）

用法:
    store = CardStore(milvus_host="localhost", milvus_port="19530")
    await store.init()
    await store.insert_cards(cards)
    results = await store.search_cards(query_embedding, top_k=10)
"""

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from knowledge_cards.schemas import KnowledgeCard, CardLink

logger = logging.getLogger(__name__)

# Milvus 集合名
COLLECTION_CARDS = "knowledge_cards"
COLLECTION_SEGMENTS = "semantic_segments"

# SQLite 路径
DEFAULT_LINK_DB = "data-persistence/data/card_links.db"
# 默认向量维度
DEFAULT_DIM = 1024  # bge-large-zh-v1.5


class CardStore:
    """知识卡片 + 段落 + 链接 的统一存储层"""

    def __init__(
        self,
        milvus_host: str = "localhost",
        milvus_port: str = "19530",
        link_db_path: str = "",
        dim: int = DEFAULT_DIM,
    ):
        self.milvus_host = milvus_host
        self.milvus_port = milvus_port
        self.dim = dim

        # 找到项目根目录（data-pipeline 的上上级）
        project_root = Path(__file__).resolve().parent.parent.parent
        if not link_db_path:
            link_db_path = str(project_root / DEFAULT_LINK_DB)

        self.link_db_path = link_db_path
        self._milvus = None
        self._connected = False

    # ================================================================
    # Milvus 连接
    # ================================================================

    def _get_milvus(self):
        """延迟获取 Milvus 连接（复用已有的 MilvusStore）"""
        if self._milvus is not None:
            return self._milvus

        try:
            from storage.milvus_store import MilvusStore

            self._milvus = MilvusStore(
                host=self.milvus_host,
                port=self.milvus_port,
            )
            self._milvus.connect()
            self._connected = True
            logger.info(
                f"Milvus connected: {self.milvus_host}:{self.milvus_port}"
            )
        except ImportError:
            logger.error("Cannot import storage.milvus_store")
            raise

        return self._milvus

    async def init(self):
        """初始化所有集合和表"""
        milvus = self._get_milvus()

        # 初始化 knowledge_cards 集合
        try:
            milvus.init_collection(COLLECTION_CARDS, dim=self.dim)
            logger.info(f"Milvus collection '{COLLECTION_CARDS}' ready")
        except Exception as e:
            logger.warning(
                f"Collection '{COLLECTION_CARDS}' may already exist: {e}"
            )

        # 初始化 semantic_segments 集合
        try:
            milvus.init_collection(COLLECTION_SEGMENTS, dim=self.dim)
            logger.info(
                f"Milvus collection '{COLLECTION_SEGMENTS}' ready"
            )
        except Exception as e:
            logger.warning(
                f"Collection '{COLLECTION_SEGMENTS}' may already exist: {e}"
            )

        # 初始化 SQLite card_links 表
        self._init_link_db()
        logger.info("CardStore initialized")

    # ================================================================
    # 卡片 CRUD
    # ================================================================

    async def insert_cards(
        self,
        cards: list[KnowledgeCard],
        embeddings: Optional[list[list[float]]] = None,
    ) -> list[str]:
        """批量插入知识卡片到 Milvus

        Args:
            cards: 知识卡片列表
            embeddings: 对应的向量列表（如已预先计算）

        Returns:
            插入的 card_id 列表
        """
        if not cards:
            return []

        milvus = self._get_milvus()
        inserted_ids = []

        for i, card in enumerate(cards):
            emb = (
                embeddings[i]
                if embeddings and i < len(embeddings)
                else card.embedding
            )
            if emb is None:
                logger.warning(f"Card {card.card_id} has no embedding, skip")
                continue

            try:
                milvus.insert_chunks(
                    embeddings=[emb],
                    chunk_ids=[card.card_id],
                    chunk_texts=[card.combined_text()],
                    doc_ids=[card.doc_id],
                    chunk_indices=[i],
                    source_urls=[""],
                    collection_name=COLLECTION_CARDS,
                )
                inserted_ids.append(card.card_id)
            except Exception as e:
                logger.error(f"Failed to insert card {card.card_id}: {e}")

        logger.info(
            f"Inserted {len(inserted_ids)}/{len(cards)} cards into Milvus"
        )
        return inserted_ids

    async def search_cards(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        doc_ids_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        """向量检索知识卡片

        Args:
            query_embedding: 查询向量
            top_k: 返回数量
            doc_ids_filter: 可选的文档ID过滤

        Returns:
            搜索结果列表，每项包含 card_id, content, score 等字段
        """
        milvus = self._get_milvus()

        try:
            hits = milvus.search_similar(
                query_vector=query_embedding,
                top_k=top_k,
                doc_ids_filter=doc_ids_filter,
                collection_name=COLLECTION_CARDS,
            )

            results = []
            for hit in hits:
                results.append({
                    "card_id": hit.entity.get("card_id", ""),
                    "content": hit.entity.get("content", ""),
                    "context": hit.entity.get("context", ""),
                    "keywords": hit.entity.get("keywords", "[]"),
                    "tags": hit.entity.get("tags", "[]"),
                    "doc_id": hit.entity.get("doc_id", ""),
                    "score": hit.score,
                })

            return results

        except Exception as e:
            logger.error(f"Card search failed: {e}")
            return []

    async def search_segments(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        doc_ids_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        """向量检索语义段落（Path B fallback）"""
        milvus = self._get_milvus()

        try:
            hits = milvus.search_similar(
                query_vector=query_embedding,
                top_k=top_k,
                doc_ids_filter=doc_ids_filter,
                collection_name=COLLECTION_SEGMENTS,
            )

            results = []
            for hit in hits:
                results.append({
                    "segment_id": hit.entity.get("segment_id", ""),
                    "text": hit.entity.get("chunk_text", ""),
                    "doc_id": hit.entity.get("doc_id", ""),
                    "score": hit.score,
                })

            return results

        except Exception as e:
            logger.error(f"Segment search failed: {e}")
            return []

    async def delete_by_doc(self, doc_id: str):
        """删除指定文档的所有卡片和段落"""
        milvus = self._get_milvus()

        # Milvus 删除需要先 query 后 delete
        logger.info(f"Deleting cards and segments for doc: {doc_id}")
        # 实际删除逻辑在后续集成时完善
        pass

    async def update_retrieval_count(self, card_id: str):
        """更新卡片的检索计数（heat boost 用）"""
        # Milvus upsert — 通用 MilvusStore 可能需要扩展
        pass

    # ================================================================
    # 段落存储（Path B）
    # ================================================================

    async def insert_segments(
        self,
        segments: list,  # list[SemanticSegment]
        embeddings: list[list[float]],
    ) -> list[str]:
        """批量插入语义段落到 Milvus"""
        if not segments:
            return []

        milvus = self._get_milvus()
        inserted = []

        for i, seg in enumerate(segments):
            emb = embeddings[i] if i < len(embeddings) else None
            if emb is None:
                continue

            try:
                milvus.insert_chunks(
                    embeddings=[emb],
                    chunk_ids=[seg.segment_id],
                    chunk_texts=[seg.text],
                    doc_ids=[seg.doc_id],
                    chunk_indices=[i],
                    source_urls=[""],
                    collection_name=COLLECTION_SEGMENTS,
                )
                inserted.append(seg.segment_id)
            except Exception as e:
                logger.error(
                    f"Failed to insert segment {seg.segment_id}: {e}"
                )

        logger.info(
            f"Inserted {len(inserted)}/{len(segments)} segments"
        )
        return inserted

    # ================================================================
    # SQLite 链接图谱
    # ================================================================

    def _init_link_db(self):
        """初始化 SQLite card_links 表"""
        Path(self.link_db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.link_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS card_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link_id TEXT NOT NULL UNIQUE,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    link_type TEXT NOT NULL DEFAULT 'supports',
                    strength REAL DEFAULT 0.5,
                    reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_links_source
                ON card_links(source_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_links_target
                ON card_links(target_id)
            """)
            conn.commit()

        logger.info(f"SQLite link DB ready: {self.link_db_path}")

    def add_link(self, link: CardLink) -> bool:
        """添加一条卡片链接"""
        try:
            with sqlite3.connect(self.link_db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO card_links
                        (link_id, source_id, target_id, link_type, strength, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        link.link_id,
                        link.source_id,
                        link.target_id,
                        link.link_type,
                        link.strength,
                        link.reason,
                        link.created_at,
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to add link: {e}")
            return False

    def add_links_batch(self, links: list[CardLink]) -> int:
        """批量添加链接"""
        count = 0
        for link in links:
            if self.add_link(link):
                count += 1
        return count

    def get_links(self, card_id: str) -> list[CardLink]:
        """获取某张卡片的所有关联链接（双向）"""
        links = []
        try:
            with sqlite3.connect(self.link_db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT * FROM card_links
                    WHERE source_id = ? OR target_id = ?
                    ORDER BY strength DESC
                    """,
                    (card_id, card_id),
                ).fetchall()

                for row in rows:
                    links.append(CardLink(
                        link_id=row["link_id"],
                        source_id=row["source_id"],
                        target_id=row["target_id"],
                        link_type=row["link_type"],
                        strength=row["strength"],
                        reason=row["reason"],
                        created_at=row["created_at"],
                    ))
        except Exception as e:
            logger.error(f"Failed to get links for {card_id}: {e}")

        return links

    def get_linked_card_ids(self, card_id: str) -> list[str]:
        """获取所有直接链接的卡片ID（用于 BFS）"""
        ids = set()
        try:
            with sqlite3.connect(self.link_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT source_id, target_id FROM card_links
                    WHERE source_id = ? OR target_id = ?
                    """,
                    (card_id, card_id),
                ).fetchall()

                for source, target in rows:
                    if source != card_id:
                        ids.add(source)
                    if target != card_id:
                        ids.add(target)
        except Exception as e:
            logger.error(f"Failed to get linked IDs for {card_id}: {e}")

        return list(ids)

    async def get_cards_by_ids(
        self, card_ids: list[str]
    ) -> dict[str, dict]:
        """按 card_id 从 Milvus 批量获取卡片详情

        Args:
            card_ids: 卡片 ID 列表

        Returns:
            {card_id: {content, keywords, tags, doc_id, ...}} 映射
        """
        if not card_ids:
            return {}

        milvus = self._get_milvus()
        milvus.init_collection(COLLECTION_CARDS, dim=self.dim)
        collection = milvus.collection

        # 构建 Milvus 查询表达式
        ids_str = ", ".join(f"'{cid}'" for cid in card_ids)
        expr = f"chunk_id in [{ids_str}]"

        try:
            results = collection.query(
                expr=expr,
                output_fields=[
                    "chunk_id", "chunk_text", "doc_id",
                ],
                limit=len(card_ids) * 2,
            )
        except Exception as e:
            logger.error(f"Failed to query cards by IDs: {e}")
            return {}

        cards = {}
        for r in results:
            cid = r.get("chunk_id", "")
            combined_text = r.get("chunk_text", "")

            # 解析 combined_text 格式:
            # content: ...\nkeywords: ...\ntags: ...\ncontext: ...
            parsed = self._parse_combined_text(combined_text)
            parsed["doc_id"] = r.get("doc_id", "")
            cards[cid] = parsed

        return cards

    @staticmethod
    def _parse_combined_text(combined_text: str) -> dict:
        """解析卡片存储的组合文本格式"""
        result = {
            "content": "",
            "keywords": [],
            "tags": [],
            "context": "",
        }
        for line in combined_text.split("\n"):
            if line.startswith("content: "):
                result["content"] = line[9:]
            elif line.startswith("keywords: "):
                kw_str = line[10:]
                result["keywords"] = [
                    k.strip() for k in kw_str.split(",") if k.strip()
                ]
            elif line.startswith("tags: "):
                tag_str = line[6:]
                result["tags"] = [
                    t.strip() for t in tag_str.split(",") if t.strip()
                ]
            elif line.startswith("context: "):
                result["context"] = line[9:]
        return result

    def get_all_card_ids(self) -> list[str]:
        """获取所有已链接的卡片ID（用于 BM25 索引重建）"""
        ids = set()
        try:
            with sqlite3.connect(self.link_db_path) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT source_id FROM card_links"
                ).fetchall()
                for (sid,) in rows:
                    ids.add(sid)
                rows = conn.execute(
                    "SELECT DISTINCT target_id FROM card_links"
                ).fetchall()
                for (tid,) in rows:
                    ids.add(tid)
        except Exception as e:
            logger.error(f"Failed to get all card IDs: {e}")

        return list(ids)
