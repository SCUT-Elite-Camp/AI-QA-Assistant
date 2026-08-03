"""
BM25 关键词检索索引。

基于 rank_bm25.BM25Okapi + jieba 中文分词。
从 data/documents/ 目录加载全部已处理文档的分块，构建 BM25 索引，
支持检索和持久化（pickle）。
"""

import os
import pickle
import jieba
from rank_bm25 import BM25Okapi
from storage.document_store import DOCS_DIR, load_document

class BM25Index:
    """
    BM25 关键词索引。

    Usage:
        bm25 = BM25Index()
        bm25.build_from_documents()
        results = bm25.search("如何配置Milvus?", top_k=5)
        bm25.save("data/bm25_index.pkl")

        # 加载已有索引
        bm25 = BM25Index.load("data/bm25_index.pkl")
    """

    def __init__(self):
        self._bm25: BM25Okapi | None = None
        self._chunk_meta: list[dict] = []       # 每个分块的元数据（doc_id, chunk_id, text...）
        self._tokenized_corpus: list[list[str]] = []  # 分词后的语料库

    # ─── 构建 / 增量更新 ───────────────────────────────

    def build_from_documents(
        self,
        docs_dir: str | None = None,
        doc_ids: list[str] | None = None,
    ):
        """
        从 data/documents/ 目录下的 JSON 文件加载分块并构建 BM25Okapi 索引。

        Args:
            docs_dir: 文档目录路径，默认 DOCS_DIR
            doc_ids: 若提供则只加载指定 doc_id 的文档（增量模式）；
                     若为 None 则全量加载
        """
        if docs_dir is None:
            docs_dir = DOCS_DIR

        if not os.path.isdir(docs_dir):
            print(f"文档目录不存在: {docs_dir}，BM25 索引将为空")
            return

        doc_id_set = set(doc_ids) if doc_ids else None

        if doc_id_set is None:
            # ─── 全量模式：重置所有状态 ──────────────
            self._chunk_meta = []
            corpus_texts: list[str] = []
        else:
            # ─── 增量模式：先移除旧条目 ──────────────
            self.remove_documents(doc_ids, rebuild=False)
            corpus_texts = [" ".join(tokens) for tokens in self._tokenized_corpus]

        new_chunks = 0
        for fname in sorted(os.listdir(docs_dir)):
            if not fname.endswith(".json"):
                continue
            doc_id = fname[:-5]  # 去掉 .json 后缀

            # 增量模式：只处理指定的 doc_id
            if doc_id_set is not None and doc_id not in doc_id_set:
                continue

            data = load_document(doc_id)
            if data is None:
                continue
            for ch in data.get("chunks", []):
                text = ch.get("text", "")
                self._chunk_meta.append({
                    "chunk_id": ch.get("chunk_id", ""),
                    "doc_id": doc_id,
                    "chunk_index": ch.get("index", 0),
                    "text": text,
                })
                corpus_texts.append(text)
                new_chunks += 1

        if not corpus_texts:
            print("未找到任何分块数据，BM25 索引为空")
            return

        # jieba 分词 + 重建 BM25Okapi
        self._tokenized_corpus = [list(jieba.cut(text)) for text in corpus_texts]
        self._bm25 = BM25Okapi(self._tokenized_corpus)

        if doc_id_set:
            print(f"BM25 索引增量更新完成：处理 {len(doc_id_set)} 个文档，"
                  f"共 {len(corpus_texts)} 个分块（新增 {new_chunks} 个）")
        else:
            print(f"BM25 索引构建完成，共 {len(corpus_texts)} 个分块")

    def add_document(self, doc_id: str, docs_dir: str | None = None):
        """增量添加单个文档到 BM25 索引"""
        self.build_from_documents(docs_dir=docs_dir, doc_ids=[doc_id])

    def add_documents(self, doc_ids: list[str], docs_dir: str | None = None):
        """增量添加多个文档到 BM25 索引"""
        self.build_from_documents(docs_dir=docs_dir, doc_ids=doc_ids)

    def remove_documents(self, doc_ids: list[str], rebuild: bool = True):
        """从索引中移除指定文档的所有分块。

        Args:
            doc_ids: 要移除的文档 ID 列表
            rebuild: 是否立即重建 BM25Okapi（False 时仅清理元数据，
                     调用方需要在之后手动重建，用于批量操作）
        """
        remove_set = set(doc_ids)
        keep_meta = []
        keep_tokens = []
        for meta, tokens in zip(self._chunk_meta, self._tokenized_corpus):
            if meta["doc_id"] not in remove_set:
                keep_meta.append(meta)
                keep_tokens.append(tokens)
        removed = len(self._chunk_meta) - len(keep_meta)
        self._chunk_meta = keep_meta
        self._tokenized_corpus = keep_tokens

        if rebuild and self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
        elif rebuild:
            self._bm25 = None

        if removed > 0:
            print(f"BM25 索引已移除 {removed} 个分块（{len(doc_ids)} 个文档）")

    # ─── 检索 ───────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        关键词检索。

        Args:
            query: 检索查询
            top_k: 返回前 K 个结果

        Returns:
            结果列表，每项包含 chunk_id, doc_id, chunk_index, text, score
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 索引尚未构建或加载，请先调用 build_from_documents() 或 load()")

        tokens = list(jieba.cut(query))
        scores = self._bm25.get_scores(tokens)

        # 按分数降序排序，取 top_k
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        top_indices = [idx for idx, _score in indexed_scores[:top_k]]

        results: list[dict] = []
        for idx in top_indices:
            meta = self._chunk_meta[idx].copy()
            meta["score"] = float(scores[idx])
            results.append(meta)
        return results

    # ─── 持久化 ─────────────────────────────────────

    @staticmethod
    def default_index_path() -> str:
        """默认 BM25 索引存储路径"""
        return os.path.join(os.path.dirname(DOCS_DIR), "bm25_index.pkl")

    def save(self, path: str):
        """将 BM25 索引持久化到磁盘（pickle）"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "tokenized_corpus": self._tokenized_corpus,
            "chunk_meta": self._chunk_meta,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str):
        """从磁盘加载 BM25 索引到当前实例"""
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._tokenized_corpus = data["tokenized_corpus"]
        self._chunk_meta = data["chunk_meta"]
        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
        return self

    @classmethod
    def load_from_file(cls, path: str) -> "BM25Index":
        """工厂方法：从磁盘加载并返回新的 BM25Index 实例"""
        instance = cls()
        instance.load(path)
        return instance

    # ─── 属性 ───────────────────────────────────────

    @property
    def chunk_count(self) -> int:
        return len(self._chunk_meta)

    @property
    def is_empty(self) -> bool:
        return self._bm25 is None
