"""Active lexical retrieval primitives used by Tool Layer and ingestion."""

__all__ = ["BM25Index", "EnglishAnalyzer", "DEFAULT_ENGLISH_ANALYZER_ID"]


def __getattr__(name):
    """Load the active retrieval primitives only when requested."""
    if name == "BM25Index":
        from retrieval.bm25_index import BM25Index

        return BM25Index
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
