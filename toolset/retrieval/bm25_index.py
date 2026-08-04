"""Production BM25 index with the project English analyzer."""

import json
import os
import pickle

from rank_bm25 import BM25Okapi
from retrieval.english_analyzer import EnglishAnalyzer
from storage.document_store import DOCS_DIR


class BM25Index:
    """Build, query, and persist the lexical chunk index.

    Usage:
        bm25 = BM25Index()
        bm25.build_from_documents()
        results = bm25.search("How do I configure Milvus?", top_k=5)
        bm25.save("data/bm25_index.pkl")
        bm25 = BM25Index.load("data/bm25_index.pkl")
    """

    def __init__(self, analyzer: EnglishAnalyzer | None = None):
        self._analyzer = analyzer or EnglishAnalyzer()
        self._bm25: BM25Okapi | None = None
        self._chunk_meta: list[dict] = []
        self._tokenized_corpus: list[list[str]] = []

    def build_from_documents(self, docs_dir: str | None = None):
        """Build BM25 from all processed document chunks."""
        if docs_dir is None:
            docs_dir = DOCS_DIR

        self._bm25 = None
        self._chunk_meta = []
        self._tokenized_corpus = []
        corpus_texts: list[str] = []

        if not os.path.isdir(docs_dir):
            print(f"Document directory does not exist: {docs_dir}; BM25 is empty")
            return

        for fname in sorted(os.listdir(docs_dir)):
            if not fname.endswith(".json"):
                continue
            doc_id = fname[:-5]
            document_path = os.path.join(docs_dir, fname)
            try:
                with open(document_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
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
            print("No document chunks found; BM25 is empty")
            return

        self._tokenized_corpus = [
            self._analyzer.analyze(text)
            for text in corpus_texts
        ]
        self._bm25 = BM25Okapi(self._tokenized_corpus)
        print(f"BM25 index built with {len(corpus_texts)} chunks")

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the highest-scoring chunks for an English query."""
        if self._bm25 is None:
            raise RuntimeError(
                "BM25 index is unavailable; build or load it before searching"
            )

        tokens = self._analyzer.analyze(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)

        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        top_indices = [idx for idx, _score in indexed_scores[:top_k]]

        results: list[dict] = []
        for idx in top_indices:
            meta = self._chunk_meta[idx].copy()
            meta["score"] = float(scores[idx])
            results.append(meta)
        return results

    @staticmethod
    def default_index_path() -> str:
        """Return the default persisted-index path."""
        return os.path.join(os.path.dirname(DOCS_DIR), "bm25_index.pkl")

    def save(self, path: str):
        """Persist the tokenized index with its analyzer identity."""
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        data = {
            "analyzer_id": self._analyzer.analyzer_id,
            "tokenized_corpus": self._tokenized_corpus,
            "chunk_meta": self._chunk_meta,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str):
        """Load an index only when it matches the active analyzer."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        stored_analyzer_id = data.get("analyzer_id")
        if stored_analyzer_id != self._analyzer.analyzer_id:
            raise ValueError(
                "BM25 index analyzer mismatch: "
                f"expected {self._analyzer.analyzer_id}, "
                f"got {stored_analyzer_id or 'legacy_jieba_or_unknown'}; "
                "rebuild the BM25 index"
            )
        self._tokenized_corpus = data["tokenized_corpus"]
        self._chunk_meta = data["chunk_meta"]
        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
        else:
            self._bm25 = None
        return self

    @classmethod
    def load_from_file(cls, path: str) -> "BM25Index":
        """Create an instance from a compatible persisted index."""
        instance = cls()
        instance.load(path)
        return instance

    @property
    def chunk_count(self) -> int:
        return len(self._chunk_meta)

    @property
    def analyzer_id(self) -> str:
        """Return the analyzer identity used for indexing and querying."""
        return self._analyzer.analyzer_id

    @property
    def is_empty(self) -> bool:
        return self._bm25 is None
