__all__ = [
    "BM25Index",
    "CrossEncoderReranker",
    "DEFAULT_RERANK_MODEL",
    "DEFAULT_RERANK_REVISION",
    "EnglishAnalyzer",
    "DEFAULT_ENGLISH_ANALYZER_ID",
    "OpenAICompatibleQueryRewriter",
    "QueryRewriter",
    "QueryRouter",
    "RetrievalObservation",
    "RetrievalOrchestrator",
    "RetrievalOrchestratorConfig",
    "RetrievalPath",
    "RewriteConfig",
    "RouteDecision",
    "weighted_rrf",
    "weighted_rrf_with_reserves",
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
    if name in {"RetrievalPath", "weighted_rrf", "weighted_rrf_with_reserves"}:
        from retrieval.fusion import (
            RetrievalPath,
            weighted_rrf,
            weighted_rrf_with_reserves,
        )

        exports = {
            "RetrievalPath": RetrievalPath,
            "weighted_rrf": weighted_rrf,
            "weighted_rrf_with_reserves": weighted_rrf_with_reserves,
        }
        return exports[name]
    if name in {
        "RetrievalObservation",
        "RetrievalOrchestrator",
        "RetrievalOrchestratorConfig",
    }:
        from retrieval.orchestrator import (
            RetrievalObservation,
            RetrievalOrchestrator,
            RetrievalOrchestratorConfig,
        )

        exports = {
            "RetrievalObservation": RetrievalObservation,
            "RetrievalOrchestrator": RetrievalOrchestrator,
            "RetrievalOrchestratorConfig": RetrievalOrchestratorConfig,
        }
        return exports[name]
    if name in {
        "OpenAICompatibleQueryRewriter",
        "QueryRewriter",
        "RewriteConfig",
    }:
        from retrieval.query_rewriter import (
            OpenAICompatibleQueryRewriter,
            QueryRewriter,
            RewriteConfig,
        )

        exports = {
            "OpenAICompatibleQueryRewriter": OpenAICompatibleQueryRewriter,
            "QueryRewriter": QueryRewriter,
            "RewriteConfig": RewriteConfig,
        }
        return exports[name]
    if name in {"QueryRouter", "RouteDecision"}:
        from retrieval.query_router import QueryRouter, RouteDecision

        exports = {
            "QueryRouter": QueryRouter,
            "RouteDecision": RouteDecision,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
