from __future__ import annotations

import json
import os
import pickle

from rank_bm25 import BM25Okapi

from retrieval.english_analyzer import EnglishAnalyzer
from storage.document_store import DOCS_DIR
from storage.filtering import matches_filters


class SectionBM25Index:
    """Persisted lexical index over canonical Section navigation text."""

    FORMAT_VERSION = 1

    def __init__(self, analyzer: EnglishAnalyzer | None = None) -> None:
        self.analyzer = analyzer or EnglishAnalyzer()
        self.rows: list[dict] = []
        self.corpus: list[list[str]] = []
        self.index: BM25Okapi | None = None

    def build_from_documents(self, docs_dir: str | None = None) -> None:
        directory = docs_dir or DOCS_DIR
        self.rows, self.corpus, self.index = [], [], None
        if not os.path.isdir(directory):
            return
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                    document = json.load(handle)
            except (OSError, ValueError, TypeError):
                continue
            if document.get("active_version", True) is not True:
                continue
            doc_id = str(document.get("doc_id") or filename[:-5])
            for section in document.get("sections") or []:
                text = str(section.get("navigation_text") or "").strip()
                if not text or not section.get("id"):
                    continue
                self.rows.append({
                    "section_id": str(section["id"]), "doc_id": doc_id,
                    "version_id": str(document.get("version_id") or ""),
                    "space": str(document.get("space") or ""),
                    "doc_type": str(document.get("doc_type") or ""),
                    "navigation_text": text,
                })
                self.corpus.append(self.analyzer.analyze(text))
        if self.corpus:
            self.index = BM25Okapi(self.corpus)

    def search(self, query: str, *, top_k: int, filters: dict | None = None) -> list[dict]:
        if self.index is None:
            return []
        tokens = self.analyzer.analyze(query)
        if not tokens:
            return []
        scores = self.index.get_scores(tokens)
        ranked = sorted(
            (
                (index, float(score)) for index, score in enumerate(scores)
                if matches_filters(self.rows[index], filters)
            ),
            key=lambda value: (-value[1], self.rows[value[0]]["section_id"]),
        )
        return [
            {**self.rows[index], "score": score}
            for index, score in ranked[:top_k] if score > 0
        ]

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump({
                "format_version": self.FORMAT_VERSION,
                "analyzer_id": self.analyzer.analyzer_id,
                "rows": self.rows,
                "corpus": self.corpus,
            }, handle)

    @classmethod
    def load(cls, path: str) -> "SectionBM25Index":
        with open(path, "rb") as handle:
            value = pickle.load(handle)
        instance = cls()
        if value.get("format_version") != cls.FORMAT_VERSION:
            raise ValueError("section BM25 format mismatch; rebuild the index")
        if value.get("analyzer_id") != instance.analyzer.analyzer_id:
            raise ValueError("section BM25 analyzer mismatch; rebuild the index")
        instance.rows = list(value.get("rows") or [])
        instance.corpus = list(value.get("corpus") or [])
        instance.index = BM25Okapi(instance.corpus) if instance.corpus else None
        return instance

    @staticmethod
    def default_index_path() -> str:
        return os.getenv(
            "SECTION_BM25_INDEX_PATH",
            os.path.join(os.path.dirname(DOCS_DIR), "section_bm25_index.pkl"),
        )
