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

    # ─── 构建 ───────────────────────────────────────

    def build_from_documents(self, docs_dir: str | None = None):
        """
        从 data/documents/ 目录下的全部 JSON 文件加载所有分块，
        用 jieba 分词后构建 BM25Okapi 索引。
        """
        if docs_dir is None:
            docs_dir = DOCS_DIR

        self._chunk_meta = []
        corpus_texts: list[str] = []

        # 遍历 docs_dir 下所有 JSON 文件
        if not os.path.isdir(docs_dir):
            print(f"文档目录不存在: {docs_dir}，BM25 索引将为空")
            return

        for fname in sorted(os.listdir(docs_dir)):
            if not fname.endswith(".json"):
                continue
            doc_id = fname[:-5]  # 去掉 .json 后缀
            data = load_document(doc_id)
            if data is None:
                continue
            for ch in data.get("chunks", []):
                self._chunk_meta.append({
                    "chunk_id": ch.get("chunk_id", ""),
                    "doc_id": doc_id,
                    "chunk_index": ch.get("index", 0),
                    "text": ch.get("text", ""),
                })
                corpus_texts.append(ch.get("text", ""))

        if not corpus_texts:
            print("未找到任何分块数据，BM25 索引为空")
            return

        # jieba 分词
        self._tokenized_corpus = [list(jieba.cut(text)) for text in corpus_texts]
        self._bm25 = BM25Okapi(self._tokenized_corpus)
        print(f"BM25 索引构建完成，共 {len(corpus_texts)} 个分块")

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
