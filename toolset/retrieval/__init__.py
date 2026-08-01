__all__ = [
    "BM25Index",
    "CrossEncoderReranker",
    "DEFAULT_RERANK_MODEL",
    "DEFAULT_RERANK_REVISION",
    "EnglishAnalyzer",
    "DEFAULT_ENGLISH_ANALYZER_ID",
]


def __getattr__(name):
    """Load retrieval implementations only when callers request them."""
    if name == "BM25Index":
        from retrieval.bm25_index import BM25Index

        return BM25Index
    if name in {
        "CrossEncoderReranker",
        "DEFAULT_RERANK_MODEL",
        "DEFAULT_RERANK_REVISION",
    }:
        from retrieval.reranker import (
            DEFAULT_RERANK_MODEL,
            DEFAULT_RERANK_REVISION,
            CrossEncoderReranker,
        )

        exports = {
            "CrossEncoderReranker": CrossEncoderReranker,
            "DEFAULT_RERANK_MODEL": DEFAULT_RERANK_MODEL,
            "DEFAULT_RERANK_REVISION": DEFAULT_RERANK_REVISION,
        }
        return exports[name]
    if name in {"EnglishAnalyzer", "DEFAULT_ENGLISH_ANALYZER_ID"}:
        from retrieval.english_analyzer import (
            DEFAULT_ENGLISH_ANALYZER_ID,
            EnglishAnalyzer,
        )

        exports = {
            "EnglishAnalyzer": EnglishAnalyzer,
            "DEFAULT_ENGLISH_ANALYZER_ID": DEFAULT_ENGLISH_ANALYZER_ID,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
